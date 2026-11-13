"""Resposta cortada no limite de tokens de saída: nova tentativa com o dobro do limite, e limite do orçamento pelo tamanho."""

import pytest

from atest.llm import MAX_OUTPUT_TOKENS, LlmSession
from atest.llm_schemas import QuoteReview
from atest.providers import ProviderError
from atest.providers.anthropic import AnthropicProvider
from atest.providers.base import Request


def _session(cfg, errors: list[Exception]) -> tuple[LlmSession, list[int]]:
    session, seen = LlmSession(None, cfg, "04171245"), []

    def fake(task, parts, output, *, system, fast, max_tokens, meta):
        seen.append(max_tokens)
        if errors:
            raise errors.pop(0)
        return "ok"

    session._ask = fake
    return session, seen


def test_truncated_answer_retries_once_with_a_bigger_limit(cfg):
    session, seen = _session(cfg, [ProviderError("cortada", truncated=True)])
    assert session.ask("quote_review", [], QuoteReview, max_tokens=5000) == "ok" and seen == [5000, 10000]
    session, seen = _session(cfg, [ProviderError("cortada", truncated=True)])
    assert session.ask("photos", [], QuoteReview, max_tokens=12000) == "ok" and seen == [12000, MAX_OUTPUT_TOKENS]


def test_other_errors_and_a_second_cut_are_not_retried(cfg):
    session, seen = _session(cfg, [ProviderError("recusa")])
    with pytest.raises(ProviderError):
        session.ask("quote_review", [], QuoteReview, max_tokens=4000)
    assert seen == [4000]
    session, seen = _session(cfg, [ProviderError("cortada", truncated=True), ProviderError("cortada de novo", truncated=True)])
    with pytest.raises(ProviderError):
        session.ask("quote_review", [], QuoteReview, max_tokens=4000)
    assert seen == [4000, 8000]  # uma tentativa a mais só
    session, seen = _session(cfg, [ProviderError("cortada", truncated=True)])
    with pytest.raises(ProviderError):
        session.ask("photos", [], QuoteReview, max_tokens=MAX_OUTPUT_TOKENS)  # já no teto: não há como dar mais espaço


def test_anthropic_marks_max_tokens_as_truncated():
    req = Request(task="quote_review", system="", parts=[], model="m", max_tokens=4000)
    with pytest.raises(ProviderError) as e:
        AnthropicProvider._check("max_tokens", req)
    assert e.value.truncated
    with pytest.raises(ProviderError) as e:
        AnthropicProvider._check("refusal", req)
    assert not e.value.truncated
