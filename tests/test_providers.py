"""Camada de provedores (Anthropic, OpenAI, Gemini, IARA), roteamento por tarefa, contingência, cache e métricas de validação."""

import io
import sys
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from atest import llm_schemas, providers
from atest.batch import BatchRunner
from atest.config import missing_keys
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
    assert set(providers.PROVIDERS) >= {"anthropic", "openai", "google", "iara"}


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


# --------------------------------------------------------------------------- IARA GenAI (Itaú)
class FakeIara:
    """Cliente IARA de teste: `chat.completions.create` devolve respostas em fila (objeto, dict ou exceção)."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _completion(content, finish="stop", prompt=100, completion=20, cached=30, model="gpt-4.1-2025-04-14"):
    return SimpleNamespace(
        id="chatcmpl-1",
        model=model,
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content, refusal=None))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, prompt_tokens_details=SimpleNamespace(cached_tokens=cached)),
    )


class HttpError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def _pdf(text: str) -> bytes:
    """PDF mínimo de uma página com o texto (para o pdf_mode = "text")."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>stream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    out.write("".join(f"{off:010d} 00000 n \n" for off in offsets).encode())
    out.write(f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def test_iara_conversion_text_image_and_pdf():
    from atest.providers.iara import convert

    req = _req(TextPart("oi"), ImagePart(b"img", "image/png"), DocumentPart(b"%PDF", title="certificate.pdf"))
    system, user = convert(req, Output)
    assert system == {"role": "system", "content": "sys"} and user["role"] == "user"
    assert [c["type"] for c in user["content"]] == ["text", "image_url", "file"]
    assert user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert user["content"][2]["file"]["filename"] == "certificate.pdf"
    assert user["content"][2]["file"]["file_data"].startswith("data:application/pdf;base64,")
    # sem response_format com schema, o schema vai no prompt de sistema
    assert '"response"' in convert(req, Output, json_mode="prompt")[0]["content"]


def test_iara_pdf_as_text():
    pytest.importorskip("pypdf")
    from atest.providers.iara import convert

    _, user = convert(_req(DocumentPart(_pdf("Laudo ART 123"), title="art.pdf")), Output, pdf_mode="text")
    assert user["content"][0]["type"] == "text"
    assert user["content"][0]["text"].startswith("[PDF: art.pdf]") and "Laudo ART 123" in user["content"][0]["text"]


@pytest.mark.parametrize(
    "output",
    [llm_schemas.AttachmentIdentification, llm_schemas.ScopeReading, llm_schemas.QuoteReview, llm_schemas.PhotoAnalysis, llm_schemas.AssessmentText],
)
def test_iara_strict_schema_closes_every_object(output):
    from atest.providers.iara import strict_schema

    schema = strict_schema(output)
    objects = []

    def collect(node):
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                objects.append(node)
            for k, v in node.items():
                if k in ("properties", "$defs"):
                    for s in v.values():
                        collect(s)
                else:
                    collect(v)
        elif isinstance(node, list):
            for v in node:
                collect(v)

    collect(schema)
    assert objects and all(o["additionalProperties"] is False and o["required"] == list(o["properties"]) for o in objects)
    # os nomes dos campos são preservados (nenhum campo some por se chamar como palavra do JSON Schema)
    assert set(schema["properties"]) == set(output.model_json_schema()["properties"])


def test_iara_generate_parses_json_usage_and_params():
    from atest.providers.iara import IaraProvider

    fake = FakeIara(_completion('```json\n{"response": "ok"}\n```'))
    r = IaraProvider(client=fake).generate(_req(TextPart("x")), Output)
    assert r.obj == Output(response="ok") and r.resolved_model == "gpt-4.1-2025-04-14" and r.response_id == "chatcmpl-1"
    assert (r.usage.input, r.usage.output, r.usage.cache_read_tokens) == (70, 20, 30)
    kw = fake.calls[0]
    assert kw["model"] == "m" and kw["max_tokens"] == 100 and kw["enable_polling"] is True
    assert kw["response_format"]["type"] == "json_schema" and kw["response_format"]["json_schema"]["strict"] is True
    assert kw["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert "reasoning_effort" not in kw

    # resposta em dict (formato alternativo do SDK) e json_mode = "json_object"
    fake = FakeIara({"id": "x", "model": "m", "choices": [{"finish_reason": "stop", "message": {"content": '{"response": "dict"}'}}]})
    r = IaraProvider(client=fake, json_mode="json_object", enable_polling=False).generate(_req(TextPart("x")), Output)
    assert r.obj.response == "dict" and r.usage.input == 0
    assert fake.calls[0]["response_format"] == {"type": "json_object"} and "enable_polling" not in fake.calls[0]


def test_iara_errors_and_retries(monkeypatch):
    from atest.providers import iara

    monkeypatch.setattr(iara.time, "sleep", lambda s: None)
    with pytest.raises(ProviderError, match="max_tokens") as e:
        iara.IaraProvider(client=FakeIara(_completion('{"resp', finish="length"))).generate(_req(TextPart("x")), Output)
    assert not e.value.transient
    with pytest.raises(ProviderError, match="fora do schema"):
        iara.IaraProvider(client=FakeIara(_completion('{"outro": 1}'))).generate(_req(TextPart("x")), Output)
    # 429 / 5xx: repete até max_retries e, se esgotar, sinaliza erro transitório (aciona a contingência)
    fake = FakeIara(HttpError(429), HttpError(503), _completion('{"response": "ok"}'))
    assert iara.IaraProvider(client=fake, max_retries=2).generate(_req(TextPart("x")), Output).obj.response == "ok"
    with pytest.raises(ProviderError) as e:
        iara.IaraProvider(client=FakeIara(HttpError(429), HttpError(429)), max_retries=1).generate(_req(TextPart("x")), Output)
    assert e.value.transient
    with pytest.raises(ProviderError) as e:
        iara.IaraProvider(client=FakeIara(HttpError(400))).generate(_req(TextPart("x")), Output)
    assert not e.value.transient
    with pytest.raises(ValueError):
        iara.IaraProvider(json_mode="xml")


def test_iara_backend_per_model(monkeypatch):
    from atest.providers import iara

    created = []

    class FakeSdk:
        def __init__(self, **kw):
            created.append(kw)
            self.chat = FakeIara(_completion('{"response": "ok"}')).chat

    monkeypatch.setitem(sys.modules, "iaragenai", SimpleNamespace(IaraGenAI=FakeSdk))
    monkeypatch.setenv("IARA_CLIENT_ID", "id")
    monkeypatch.setenv("IARA_CLIENT_SECRET", "secret")
    monkeypatch.delenv("IARA_ACCESS_TOKEN", raising=False)
    p = iara.IaraProvider(environment="homol")
    p.generate(Request(task="t", system="s", parts=[TextPart("x")], model="bedrock/anthropic.claude-x:0", max_tokens=10), Output)
    p.generate(Request(task="t", system="s", parts=[TextPart("x")], model="gpt-4.1", max_tokens=10), Output)
    assert [c["provider"] for c in created] == ["bedrock", "azure_openai"]
    assert created[0] == {"client_id": "id", "client_secret": "secret", "environment": "homol", "provider": "bedrock"}
    assert iara.split_backend("bedrock/anthropic.claude-x:0", "azure_openai") == ("bedrock", "anthropic.claude-x:0")
    assert iara.split_backend("org/modelo", "azure_openai") == ("azure_openai", "org/modelo")


def test_iara_options_reach_the_provider_and_credentials_need_both_vars(cfg, monkeypatch):
    from atest.providers.iara import IaraProvider

    c = cfg.with_overrides(**{"models.main": "iara:gpt-4.1", "llm.provider_options": {"iara": {"environment": "prod", "pdf_mode": "text"}}})
    providers.clear_instances()
    try:
        p = ProviderClient(c).provider("iara")
        assert isinstance(p, IaraProvider) and p.environment == "prod" and p.pdf_mode == "text" and p.backend == "azure_openai"
    finally:
        providers.clear_instances()
    monkeypatch.setenv("IARA_CLIENT_ID", "id")
    monkeypatch.delenv("IARA_CLIENT_SECRET", raising=False)
    assert "iara" in missing_keys(c)
    monkeypatch.setenv("IARA_CLIENT_SECRET", "secret")
    assert "iara" not in missing_keys(c)


# --------------------------------------------------------------------------- seletor de provedor do painel
def test_panel_provider_choices_come_from_config(cfg, monkeypatch):
    from atest.api import provider_choices

    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    for v in ("IARA_CLIENT_ID", "IARA_CLIENT_SECRET"):
        monkeypatch.delenv(v, raising=False)
    choices = provider_choices(cfg)
    # openai e google estão com enabled = false no settings.toml
    assert [c.id for c in choices] == ["anthropic", "iara"]
    assert choices[0].main == cfg.models.main and choices[0].available
    assert not choices[1].available and choices[1].credentials == ["IARA_CLIENT_ID", "IARA_CLIENT_SECRET"]
    assert (choices[1].main, choices[1].fast) == ("iara:gpt-4.1", "iara:gpt-4.1-mini")

    # o provedor dos modelos configurados vem primeiro, com os modelos de [models], mesmo se escondido no painel
    itau = cfg.with_overrides(**{"models.main": "iara:gpt-4.1", "models.fast": "iara:gpt-4.1", "panel.providers.anthropic.enabled": False})
    assert [(c.id, c.fast) for c in provider_choices(itau)] == [("iara", "iara:gpt-4.1")]

    # modelo sem prefixo ganha o do provedor; prefixo de outro provedor é erro de configuração
    assert cfg.with_overrides(**{"panel.providers": {"iara": {"main": "x", "fast": "y"}}}).panel.providers["iara"].main == "iara:x"
    with pytest.raises(ValidationError):
        cfg.with_overrides(**{"panel.providers": {"iara": {"main": "openai:x", "fast": "y"}}})


def test_run_with_chosen_provider_ignores_other_providers_overrides(cfg):
    from fastapi import HTTPException

    from atest.api import RunManager, RunRequest

    base = cfg.with_overrides(**{"models.tasks": {"photos": "anthropic:a", "scope": "iara:b"}, "models.fallback": {"main": "anthropic:c"}})
    manager = RunManager(base, database=None)
    run = manager.run_settings(RunRequest(tickets=["1"], provider="iara"))
    assert (run.models.main, run.models.fast) == ("iara:gpt-4.1", "iara:gpt-4.1-mini")
    assert run.models.tasks == {"scope": "iara:b"} and run.models.fallback == {}
    # modelos escolhidos no painel valem sobre os do provedor
    run = manager.run_settings(RunRequest(tickets=["1"], provider="iara", main_model="iara:gpt-5"))
    assert run.models.main == "iara:gpt-5" and run.models.fast == "iara:gpt-4.1-mini"
    # sem provedor, nada muda (compatível com chamadas antigas da API)
    assert manager.run_settings(RunRequest(tickets=["1"])).models.tasks == base.models.tasks
    with pytest.raises(HTTPException) as e:
        manager.run_settings(RunRequest(tickets=["1"], provider="openai"))  # existe, mas está com enabled = false
    assert e.value.status_code == 422


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
