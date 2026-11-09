"""Observabilidade: logs estruturados (JSON por linha) com contexto de execução, chamado e etapa.

Cada evento relevante (início/fim de etapa, chamada ao modelo, lote enviado, erro, feedback) vira uma linha em
output/logs/atest.jsonl, pronta para ser lida por qualquer ferramenta de logs (Datadog, Splunk, ELK, CloudWatch).
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
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


class ConsoleFormatter(logging.Formatter):
    """Linha curta e legível para o terminal."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = " ".join(x for x in (current_ticket.get(), current_stage.get()) if x)
        base = f"{datetime.fromtimestamp(record.created):%H:%M:%S} {record.levelname:<7} {ctx + ' · ' if ctx else ''}{record.getMessage()}"
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
        c.setLevel(logging.WARNING)  # no console, só avisos; o detalhe fica no JSON
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
