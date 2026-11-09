"""Camada de provedores (Anthropic, OpenAI, Gemini), roteamento por tarefa, contingência, cache e métricas de validação."""

import pytest
from pydantic import BaseModel

from atest import providers
from atest.batch import BatchRunner
from atest.llm import LlmSession, ProviderClient
from atest.providers.base import DocumentPart, ImagePart, Provider, ProviderError, ProviderResponse, Request, TextPart, Usage
from atest.validation import DatasetCatalog, Stats


class Output(BaseModel):
    response: str


class FakeProvider(Provider):
    """Provedor de teste: responde com o próprio nome; pode falhar nas primeiras chamadas."""

    def __init__(self, name: str, failures: int = 0, transient: bool = True):
        self.name, self.failures, self.transient, self.calls = name, failures, transient, []

    def generate(self, req, output):
        self.calls.append(req)
        if self.failures:
            self.failures -= 1
            raise ProviderError("overloaded", transient=self.transient)
        return ProviderResponse(obj=output(response=f"{self.name}:{req.model}"), usage=Usage(input=10, output=2), resolved_model=f"{req.model}-2026")


def _req(*parts):
    return Request(task="scope", system="sys", parts=list(parts), model="m", max_tokens=100)


# --------------------------------------------------------------------------- nomes e conversões
def test_split_model_accepts_provider_prefix():
    assert providers.split_model("openai:gpt-x") == ("openai", "gpt-x")
    assert providers.split_model("google:gemini-y") == ("google", "gemini-y")
    assert providers.split_model("claude-sonnet-5-5") == ("anthropic", "claude-sonnet-5-5")
    assert set(providers.PROVIDERS) >= {"anthropic", "openai", "google"}


def test_cache_key_changes_with_provider_content_and_schema():
    class Other(BaseModel):
        x: int

    r = _req(TextPart("a"), ImagePart(b"\x01"))
    assert r.key(Output, "anthropic") == _req(TextPart("a"), ImagePart(b"\x01")).key(Output, "anthropic")
    assert r.key(Output, "anthropic") != r.key(Output, "openai")
    assert r.key(Output, "anthropic") != _req(TextPart("a"), ImagePart(b"\x02")).key(Output, "anthropic")
    assert r.key(Output, "anthropic") != r.key(Other, "anthropic")


def test_openai_conversion():
    from atest.providers.openai import convert

    msgs = convert(_req(TextPart("oi"), ImagePart(b"img", "image/png"), DocumentPart(b"%PDF", title="certificate.pdf")))
    kinds = [c["type"] for c in msgs[0]["content"]]
    assert msgs[0]["role"] == "user" and kinds == ["input_text", "input_image", "input_file"]
    assert msgs[0]["content"][1]["image_url"].startswith("data:image/png;base64,")
    assert msgs[0]["content"][2]["filename"] == "certificate.pdf"


def test_gemini_conversion():
    pytest.importorskip("google.genai")
    from atest.providers.google import convert

    content = convert(_req(TextPart("oi"), ImagePart(b"img")))
    assert content[0].role == "user" and len(content[0].parts) == 2
    assert content[0].parts[1].inline_data.mime_type == "image/jpeg"


def test_anthropic_conversion_caches_system():
    from atest.providers.anthropic import AnthropicProvider

    p = AnthropicProvider(client=object())._params(_req(TextPart("oi"), ImagePart(b"img"), DocumentPart(b"%PDF")))
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert [b["type"] for b in p["messages"][0]["content"]] == ["text", "image", "document"]


# --------------------------------------------------------------------------- roteamento, contingência e cache
def test_routing_by_task_and_fallback(cfg):
    main, backup = FakeProvider("main", failures=1), FakeProvider("backup")
    c = cfg.with_overrides(**{"models.tasks": {"scope": "main:modelo-a"}, "models.fallback": {"main": "backup:modelo-b"}})
    session = LlmSession(ProviderClient(c, {"main": main, "backup": backup}), c, "00000001")
    out = session.ask("scope", [TextPart("x")], Output)
    # a tarefa foi para o modelo configurado; o erro transitório caiu na contingência
    assert main.calls[0].model == "modelo-a" and out.response == "backup:modelo-b"
    ch = session.calls[0]
    assert ch.provider == "backup" and ch.model == "backup:modelo-b" and ch.resolved_model == "modelo-b-2026"
    assert ch.prompt_version == c.prompts.version and len(ch.prompt_hash) >= 8 and ch.schema_hash


def test_permanent_error_skips_fallback(cfg):
    main = FakeProvider("main", failures=1, transient=False)
    c = cfg.with_overrides(**{"models.tasks": {"scope": "main:a"}, "models.fallback": {"main": "backup:b"}})
    with pytest.raises(ProviderError):
        LlmSession(ProviderClient(c, {"main": main, "backup": FakeProvider("backup")}), c, "1").ask("scope", [TextPart("x")], Output)


def test_disk_cache_avoids_second_call(cfg, tmp_path):
    p = FakeProvider("main")
    c = cfg.with_overrides(**{"llm.use_disk_cache": True, "paths.cache": tmp_path, "models.tasks": {"scope": "main:a"}})
    client = ProviderClient(c, {"main": p})
    for _ in range(2):
        s = LlmSession(client, c, "1")
        s.ask("scope", [TextPart("mesma entrada")], Output)
    assert len(p.calls) == 1 and s.calls[0].from_cache and s.calls[0].resolved_model == "a-2026"


# --------------------------------------------------------------------------- métricas de validação
def test_kappa():
    assert Stats.kappa([[5, 0], [0, 5]]) == 1
    assert Stats.kappa([[5, 5], [5, 5]]) == 0
    assert Stats.kappa([[20, 5], [10, 15]]) == pytest.approx(0.4)


def test_sample_is_reproducible():
    ids = [str(i) for i in range(100)]
    sample = DatasetCatalog.sample
    assert sample(ids, 10) == sample(ids, 10) and len(sample(ids, 10)) == 10 and sample(ids, None) == ids


def test_validation_report_with_and_without_noise(cfg, demo):
    clean = BatchRunner(cfg).run(demo).validation
    assert clean.n == 13 and clean.accuracy.value == 1 and clean.kappa == 1 and clean.gate_passed
    assert sum(map(sum, clean.matrix)) == 13 and not clean.mismatches and clean.score_mae <= cfg.validation.score_error_max

    noisy = BatchRunner(cfg.with_overrides(**{"validation.simulated_noise": 0.5})).run(demo).validation
    assert noisy.accuracy.value < 1 and noisy.mismatches
    assert noisy.accuracy.ci_low <= noisy.accuracy.value <= noisy.accuracy.ci_high
