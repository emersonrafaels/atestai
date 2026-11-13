"""Observabilidade: logs estruturados (JSON por linha) com contexto de execução, chamado e etapa.

Cada evento relevante (início/fim de etapa, chamada ao modelo, lote enviado, erro, feedback) vira uma linha em
output/logs/atest.jsonl, pronta para ser lida por qualquer ferramenta de logs (Datadog, Splunk, ELK, CloudWatch).

No terminal, os mesmos eventos aparecem em português, uma linha por evento, para acompanhar a análise ao vivo:
início e fim de cada chamado e etapa, cada chamada ao modelo (tempo, tokens, custo) e, enquanto se espera o modelo
ou um lote, um aviso periódico ("ainda aguardando há 60 s") que vira alerta de possível travamento.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings

current_run: contextvars.ContextVar[str | None] = contextvars.ContextVar("run", default=None)
current_ticket: contextvars.ContextVar[str | None] = contextvars.ContextVar("ticket", default=None)
current_stage: contextvars.ContextVar[str | None] = contextvars.ContextVar("stage", default=None)

log = logging.getLogger("atest")
_DEFAULT_FIELDS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por evento, com o contexto (execução, chamado, etapa) e os campos extras."""

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "run": current_run.get(),
            "ticket": current_ticket.get(),
            "stage": current_stage.get(),
        }
        event.update({k: v for k, v in record.__dict__.items() if k not in _DEFAULT_FIELDS})
        if record.exc_info:
            event["error"] = self.formatException(record.exc_info)
        return json.dumps({k: v for k, v in event.items() if v is not None}, ensure_ascii=False, default=str)


STAGE_PT = {
    "checklist": "Checklist", "scope": "Escopo", "quote": "Orçamento", "photos": "Fotos", "documents": "Documentos",
    "score": "Score", "assessment": "Parecer",
}
LEVEL_PT = {"DEBUG": "DEBUG", "INFO": "INFO", "WARNING": "AVISO", "ERROR": "ERRO", "CRITICAL": "ERRO"}


def _num(v: Any, digits: int = 1) -> str:
    """Número no formato brasileiro (1.234,5)."""
    try:
        return f"{float(v):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(v)


def _task(name: str | None) -> str:
    from .formatting import TASK_PT

    return TASK_PT.get(name or "", (name or "").replace("_", " "))


def _rec(value: str | None) -> str:
    from .domain import Recommendation

    try:
        return Recommendation(value).label
    except ValueError:
        return str(value)


def humanize(name: str, f: dict[str, Any]) -> str:
    """Texto em português de um evento, para o terminal. Evento sem texto próprio sai como nome + campos."""
    stage = STAGE_PT.get(f.get("_stage") or "", f.get("_stage") or "")
    model = str(f.get("model", "")).split(":")[-1]
    if name == "run_start":
        return f"=== Execução iniciada: {f.get('tickets')} chamado(s), modo {f.get('mode')}, envio {f.get('batch_mode')}, fase {f.get('phase')}"
    if name == "run_end":
        return (f"=== Execução concluída: {f.get('assessments')} parecer(es), {f.get('errors')} erro(s), "
                f"{_num(f.get('input_tokens'), 0)} tokens de entrada, {_num(f.get('output_tokens'), 0)} de saída, US$ {_num(f.get('cost_usd'), 4)}")
    if name == "ticket_start":
        from .domain import current_catalog

        category = current_catalog().label("categories", str(f.get("category", "")))
        return f"Início da análise (esteira {f.get('workstream')}, categoria {category}, modo {f.get('mode')})"
    if name == "ticket_end":
        score = "sem score" if f.get("score") is None else f"score {f.get('score')}"
        n = len(f.get("findings") or [])
        cost, dur = _num(f.get("cost_usd"), 4), _num(f.get("duration_s"))
        return f"Fim da análise: {_rec(f.get('recommendation'))} · {score} · {n} tipo(s) de apontamento · US$ {cost} · {dur} s"
    if name == "stage_start":
        return f"Etapa {stage}: iniciada"
    if name == "stage_end":
        return f"Etapa {stage} concluída em {_num(f.get('duration_s'))} s"
    if name == "stage_error":
        return f"Etapa {stage} FALHOU após {_num(f.get('duration_s'))} s"
    if name == "llm_request":
        extra = ", ".join(x for x in (
            f"{f['images']} imagem(ns)" if f.get("images") else "", f"{f['documents']} PDF(s)" if f.get("documents") else "",
        ) if x)
        limit = f"limite {_num(float(f['timeout_s']) / 60)} min" if f.get("timeout_s") else ""
        extra = ", ".join(x for x in (extra, limit) if x)
        return f"{_task(f.get('task'))}: chamando {model}{f' ({extra})' if extra else ''}..."
    if name == "llm_waiting":
        msg = f"{_task(f.get('task'))}: ainda aguardando {model} há {_num(f.get('elapsed_s'), 0)} s"
        return msg + (" (possível travamento: confira a conexão e o provedor)" if f.get("stalled") else "")
    if name == "llm_call":
        if f.get("simulated"):
            return f"{_task(f.get('task'))}: resposta simulada em {_num(f.get('duration_s'))} s"
        origin = " (do cache)" if f.get("from_cache") else " (via lote)" if f.get("via_batch") else ""
        return (f"{_task(f.get('task'))}: resposta de {model} em {_num(f.get('duration_s'))} s{origin} · "
                f"{_num(f.get('input_tokens'), 0)} tokens de entrada, {_num(f.get('output_tokens'), 0)} de saída · US$ {_num(f.get('cost_usd'), 4)}")
    if name == "llm_fallback":
        return f"{_task(f.get('task'))}: {model} falhou ({f.get('error')}); tentando {str(f.get('fallback', '')).split(':')[-1]}"
    if name == "iara_json_mode_fallback":
        return f"{_task(f.get('task'))}: resposta da IARA fora do formato ({f.get('reason')}); repetindo em modo {f.get('to_mode')}"
    if name == "iara_bad_output":
        return (f"{_task(f.get('task'))}: resposta da IARA ilegível ({f.get('detail')}, modo {f.get('mode')}); "
                "a resposta bruta foi gravada em output/logs/atest.jsonl (evento iara_bad_output)")
    if name == "photos_retry":
        return f"Análise das fotos falhou ({f.get('error')}); tentando de novo"
    if name == "photos_chunked":
        return f"Análise das {f.get('photos')} fotos falhou; tentando em {f.get('chunks')} lotes menores"
    if name == "photos_degraded":
        return f"Fotos não analisadas ({f.get('error')}): o chamado segue com confiança reduzida para conferência manual"
    if name == "photos_quantity_unchecked":
        return f"Análise das fotos: o modelo não contou os itens {f.get('items')}; registrado nas observações do parecer"
    if name == "quote_coverage_incomplete":
        return f"Conferência do orçamento: serviços pedidos sem conferência do modelo ({'; '.join(f.get('missing') or [])})"
    if name == "documents_retry":
        return f"Leitura dos documentos falhou ({f.get('error')}); tentando de novo"
    if name == "documents_degraded":
        return f"Documentos não lidos ({f.get('error')}): o chamado segue com confiança reduzida"
    if name == "batch_sent":
        tasks = ", ".join(_task(t) for t in f.get("tasks") or [])
        return f"Lote {f.get('batch_id')} enviado a {f.get('provider')}: {f.get('requests')} pedido(s) ({tasks})"
    if name == "batch_waiting":
        return f"Lote {f.get('batch_id')} ainda em processamento há {_num(float(f.get('elapsed_s', 0)) / 60)} min"
    if name == "batch_done":
        return f"Lote {f.get('batch_id')} concluído em {_num(f.get('duration_s'))} s"
    fields = {k: v for k, v in f.items() if not k.startswith("_") and k != "event"}
    return f"{name} " + " ".join(f"{k}={v}" for k, v in fields.items()) if fields else name


class ConsoleFormatter(logging.Formatter):
    """Linha curta e legível para o terminal: hora, nível, [chamado] e o evento em português."""

    def format(self, record: logging.LogRecord) -> str:
        fields = {k: v for k, v in record.__dict__.items() if k not in _DEFAULT_FIELDS}
        name = fields.get("event")
        fields["_stage"] = current_stage.get()
        text = humanize(name, fields) if name else record.getMessage()
        ticket = current_ticket.get()
        level = LEVEL_PT.get(record.levelname, record.levelname)
        base = f"{datetime.fromtimestamp(record.created):%H:%M:%S} {level:<5} {f'[{ticket}] ' if ticket else ''}{text}"
        return base + ("\n" + self.formatException(record.exc_info) if record.exc_info else "")


def configure_logging(cfg: Settings) -> Path | None:
    """Configura o logger "atest" (arquivo JSON lines e/ou console). Devolve o caminho do arquivo, se houver."""
    root = logging.getLogger("atest")
    root.handlers.clear()
    root.setLevel(cfg.observability.level.upper())
    root.propagate = False
    target = None
    if cfg.observability.log_json:
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        target = cfg.logs_dir / "atest.jsonl"
        h = logging.FileHandler(target, encoding="utf-8")
        h.setFormatter(JsonFormatter())
        root.addHandler(h)
    if cfg.observability.log_console:
        c = logging.StreamHandler(sys.stderr)
        c.setFormatter(ConsoleFormatter())
        c.setLevel(cfg.observability.console_level.upper())  # INFO: acompanha a análise ao vivo; WARNING: só avisos e erros
        root.addHandler(c)
    return target


def event(name: str, level: int = logging.INFO, **fields: Any) -> None:
    """Registra um evento nomeado com campos estruturados."""
    log.log(level, name, extra={"event": name, **fields})


@contextmanager
def context(run: str | None = None, ticket: str | None = None) -> Iterator[None]:
    """Associa a execução e o chamado a todos os eventos registrados dentro do bloco."""
    tokens = []
    if run is not None:
        tokens.append((current_run, current_run.set(run)))
    if ticket is not None:
        tokens.append((current_ticket, current_ticket.set(ticket)))
    try:
        yield
    finally:
        for var, tok in reversed(tokens):
            var.reset(tok)


@contextmanager
def waiting(name: str, every_s: float, stalled_after: int = 3, **fields: Any) -> Iterator[None]:
    """Registra `<name>_request` e, enquanto o bloco não termina, `<name>_waiting` a cada `every_s` segundos.

    A partir de `stalled_after` avisos, o aviso sobe para WARNING com `stalled=True` (possível travamento). O aviso sai
    numa thread à parte com o mesmo contexto (execução, chamado, etapa), então aparece mesmo com a chamada parada.
    """
    event(f"{name}_request", **fields)
    if every_s <= 0:
        yield
        return
    done = threading.Event()
    ctx = contextvars.copy_context()
    t0 = time.perf_counter()

    def beat() -> None:
        n = 0
        while not done.wait(every_s):
            n += 1
            stalled = n >= stalled_after
            level = logging.WARNING if stalled else logging.INFO
            event(f"{name}_waiting", level, elapsed_s=round(time.perf_counter() - t0), stalled=stalled, **fields)

    thread = threading.Thread(target=ctx.run, args=(beat,), daemon=True, name=f"atest-{name}-heartbeat")
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(timeout=5)  # nenhum aviso de espera sai depois da resposta


@contextmanager
def timed_stage(name: str, durations: dict[str, float]) -> Iterator[None]:
    """Mede e registra a duração de uma etapa do pipeline."""
    tok = current_stage.set(name)
    t0 = time.perf_counter()
    event("stage_start")
    try:
        yield
    except Exception:
        event("stage_error", logging.ERROR, duration_s=round(time.perf_counter() - t0, 3))
        raise
    finally:
        dur = round(time.perf_counter() - t0, 3)
        durations[name] = dur
        event("stage_end", duration_s=dur)
        current_stage.reset(tok)
