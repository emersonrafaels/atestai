"""Tempo limite das chamadas ao modelo: proporcional ao pedido e com vigia para API fora do ar ou travada."""

import time

import pytest

from atest.formatting import error_message
from atest.llm import LlmSession, LlmTimeout, call_timeout, run_with_deadline
from atest.llm_schemas import AssessmentText
from atest.providers import TextPart


def test_timeout_grows_with_images_documents_and_output(cfg):
    small = call_timeout(cfg, images=0, documents=0, max_tokens=1200)
    photos = call_timeout(cfg, images=6, documents=0, max_tokens=5000)
    many = call_timeout(cfg, images=30, documents=0, max_tokens=5000)
    assert small == cfg.llm.timeout_min_s  # pedido pequeno fica no mínimo
    assert small < photos < many <= cfg.llm.timeout_max_s
    assert call_timeout(cfg, images=500) == cfg.llm.timeout_max_s  # nunca passa do máximo


def test_run_with_deadline_gives_up_on_hung_call():
    assert run_with_deadline(lambda: 42, 1, "x") == 42
    with pytest.raises(ValueError):
        run_with_deadline(lambda: (_ for _ in ()).throw(ValueError("erro do provedor")), 1, "x")
    t0 = time.perf_counter()
    with pytest.raises(LlmTimeout, match="não respondeu em 0 s"):
        run_with_deadline(lambda: time.sleep(5), 0.2, "[photos] O modelo")
    assert time.perf_counter() - t0 < 2  # desiste no prazo, sem esperar a chamada presa


class HungClient:
    """Cliente que nunca responde (API travada) e registra o limite recebido."""

    simulated = False
    via_batch = False

    def __init__(self):
        self.timeouts: list[float | None] = []

    def structured(self, *, timeout_s=None, **_):
        self.timeouts.append(timeout_s)
        time.sleep(10)


def test_session_stops_hung_call_with_clear_message(cfg):
    fast = cfg.with_overrides(**{"llm.timeout_base_s": 0, "llm.timeout_per_1k_tokens_s": 0, "llm.timeout_min_s": 1,
                                 "llm.timeout_max_s": 1, "observability.heartbeat_s": 0})
    client = HungClient()
    session = LlmSession(client, fast, "04159084")
    t0 = time.perf_counter()
    with pytest.raises(LlmTimeout) as e:
        session.ask("assessment", [TextPart("x")], AssessmentText)
    assert time.perf_counter() - t0 < 8  # 2 x 1 s + 1 s de folga
    assert client.timeouts == [1.0]  # o limite de cada tentativa chega ao provedor
    assert error_message(e.value).startswith("Falha em Redação do parecer: O modelo não respondeu em")


def test_connection_errors_in_portuguese():
    msg = error_message(RuntimeError("[photos] APIConnectionError: Connection error."))
    assert msg.startswith("Falha em Análise das fotos: não foi possível conectar à API do modelo")
    assert "não respondeu no tempo limite" in error_message(RuntimeError("[scope] APITimeoutError: Request timed out."))
