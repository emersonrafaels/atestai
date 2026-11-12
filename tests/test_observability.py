"""Logs no terminal: eventos em português e aviso periódico enquanto se espera o modelo (detecção de travamento)."""

import logging
import time

from atest.observability import ConsoleFormatter, context, humanize, log, waiting


class Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []
        self.records: list[logging.LogRecord] = []
        self.setFormatter(ConsoleFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.lines.append(self.format(record))


def test_waiting_heartbeat_and_stall_alert():
    h = Collect()
    log.addHandler(h)
    old = log.level
    log.setLevel(logging.INFO)
    try:
        with context(ticket="04159084"), waiting("llm", 0.05, stalled_after=3, task="documents", model="anthropic:claude-x", images=2):
            time.sleep(0.3)  # chamada "lenta": o aviso sai mesmo com o bloco parado
    finally:
        log.removeHandler(h)
        log.setLevel(old)
    assert "[04159084] Leitura dos documentos: chamando claude-x (2 imagem(ns))..." in h.lines[0]
    waits = [r for r in h.records if getattr(r, "event", "") == "llm_waiting"]
    assert len(waits) >= 3 and waits[0].levelno == logging.INFO
    assert waits[-1].levelno == logging.WARNING and "possível travamento" in h.lines[h.records.index(waits[-1])]
    n = len(h.records)
    time.sleep(0.15)
    assert len(h.records) == n  # ao sair do bloco, os avisos param


def test_humanize_events():
    assert humanize("stage_end", {"_stage": "documents", "duration_s": 3.25}) == "Etapa Documentos concluída em 3,2 s"
    assert humanize("llm_call", {"task": "scope", "model": "simulado (anthropic:x)", "simulated": True, "duration_s": 0.3}) == (
        "Leitura do escopo: resposta simulada em 0,3 s"
    )
    call = {"task": "photos", "model": "anthropic:m", "duration_s": 12.3, "input_tokens": 4512, "output_tokens": 830, "cost_usd": 0.021}
    line = humanize("llm_call", call)
    assert line == "Análise das fotos: resposta de m em 12,3 s · 4.512 tokens de entrada, 830 de saída · US$ 0,0210"
    assert humanize("ticket_end", {"recommendation": "approve", "score": 94, "findings": ["x"], "cost_usd": 0.1, "duration_s": 48}).startswith(
        "Fim da análise: Aprovar · score 94 · 1 tipo(s)"
    )
    assert humanize("evento_novo", {"a": 1}) == "evento_novo a=1"
