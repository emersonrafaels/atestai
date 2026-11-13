"""Pipeline completo: simulado com banco; cliente real do SDK (síncrono e Message Batches) contra servidor HTTP
simulado; e API do painel (execução, persistência, feedback, upload e métricas)."""

import json
import re
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
from fastapi.testclient import TestClient

from atest.api import create_app
from atest.batch import BatchRunner, ComponentFactory
from atest.config import BatchMode, Mode
from atest.costs import CostCalculator
from atest.database import Database
from atest.llm import BatchClient, ProviderClient
from atest.observability import configure_logging
from atest.providers.anthropic import AnthropicProvider
from atest.providers.iara import IaraProvider
from atest.repository import load_ground_truth
from atest.simulated import SimulatedClient


def test_simulated_batch_matches_ground_truth_and_persists(cfg, demo):
    configure_logging(cfg)
    database = Database(cfg.database_file)
    res = BatchRunner(cfg, database=database).run(demo)
    assert not res.errors and len(res.assessments) == 13
    assert res.evaluation.exact_recommendation == 13 and res.evaluation.checklist == 13
    assert all(p.record_id for p in res.assessments)
    assert len(database.run_assessments(res.run_id)) == 13
    assert (cfg.logs_dir / "atest.jsonl").exists()


# ----------------------------------------------------------------------------- servidor simulado da API
class FakeServer:
    """Responde /v1/messages e /v1/messages/batches a partir do gabarito."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.simulated = SimulatedClient(cfg)
        self.batches: dict[str, list] = {}
        self.requests = 0
        self.images = 0

    @staticmethod
    def _task(schema: dict) -> str:
        props = schema.get("properties", {})
        tasks = (
            ("attachments", "identify_attachments"), ("local", "scope"), ("photos", "photos"), ("documents", "documents"), ("summary", "assessment"),
        )
        for key, name in tasks:
            if key in props:
                return name
        return "quote_review"

    def answer(self, schema: dict, texts: str) -> dict:
        """Resposta do gabarito para a tarefa (identificada pelo schema) e o chamado citado no texto."""
        attachments = re.findall(r"--- Anexo (\d+): (.+?) \(", texts)
        tid = re.search(r"Chamado (\d{8})", texts).group(1)
        meta = {"ticket": tid, "attachments": [n for _, n in attachments], "indices": [int(i) for i, _ in attachments]}
        t = self._task(schema)
        if t == "assessment":
            return {"summary": "(mock)", "supplier_message": ""}
        return getattr(self.simulated, f"_{t}")(load_ground_truth(self.cfg.ground_truth_dir, tid), meta)

    def message(self, params: dict) -> dict:
        self.requests += 1
        fmt = params["output_config"]["format"]
        assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False
        assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
        content = params["messages"][0]["content"]
        self.images += sum(b["type"] == "image" for b in content)
        out = self.answer(fmt["schema"], " ".join(b["text"] for b in content if b["type"] == "text"))
        return {
            "id": "msg_mock",
            "type": "message",
            "role": "assistant",
            "model": params["model"],
            "content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 200, "cache_creation_input_tokens": 0},
        }

    def _batch_json(self, bid: str, finished: bool) -> dict:
        now = datetime.now(UTC).isoformat()
        n = len(self.batches[bid])
        return {
            "id": bid,
            "type": "message_batch",
            "processing_status": "ended" if finished else "in_progress",
            "request_counts": {"processing": 0 if finished else n, "succeeded": n if finished else 0, "errored": 0, "canceled": 0, "expired": 0},
            "created_at": now,
            "expires_at": now,
            "ended_at": now if finished else None,
            "archived_at": None,
            "cancel_initiated_at": None,
            "results_url": f"https://api.anthropic.com/v1/messages/batches/{bid}/results" if finished else None,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/messages":
            return httpx.Response(200, json=self.message(json.loads(request.content)))
        if path == "/v1/messages/batches" and request.method == "POST":
            bid = f"msgbatch_{len(self.batches) + 1:03d}"
            self.batches[bid] = json.loads(request.content)["requests"]
            return httpx.Response(200, json=self._batch_json(bid, False))
        if m := re.fullmatch(r"/v1/messages/batches/(\w+)/results", path):
            rows = [
                json.dumps({"custom_id": r["custom_id"], "result": {"type": "succeeded", "message": self.message(r["params"])}})
                for r in self.batches[m.group(1)]
            ]
            return httpx.Response(200, content="\n".join(rows).encode())
        if m := re.fullmatch(r"/v1/messages/batches/(\w+)", path):
            return httpx.Response(200, json=self._batch_json(m.group(1), True))
        return httpx.Response(404, json={"error": path})


def _sdk(server):
    return anthropic.Anthropic(api_key="sk-teste", http_client=httpx.Client(transport=httpx.MockTransport(server)), max_retries=0)


def _fake_anthropic(server) -> dict:
    """Instâncias de provedor injetadas no cliente: o SDK real da Anthropic, falando com o servidor falso."""
    return {"anthropic": AnthropicProvider(client=_sdk(server))}


def test_sync_client_through_sdk(cfg, demo):
    server = FakeServer(cfg)
    cfg_api = cfg.with_overrides(**{"execution.mode": Mode.API})
    orchestrator = ComponentFactory(cfg_api).orchestrator(ProviderClient(cfg_api, _fake_anthropic(server)))
    res = BatchRunner(cfg_api, orchestrator).run(demo)
    assert not res.errors and res.evaluation.exact_recommendation == 13
    assert server.images > 30 and res.tokens[0] == 1000 * server.requests
    cost = res.assessments[0].llm_calls[0]
    assert cost.cost_usd > 0 and res.cost_usd > 0


def test_message_batches_groups_rounds(cfg, demo):
    server = FakeServer(cfg)
    cfg_b = cfg.with_overrides(**{"execution.mode": Mode.API, "batch.kind": BatchMode.BATCH})
    client = BatchClient(cfg_b, _fake_anthropic(server))
    res = BatchRunner(cfg_b, ComponentFactory(cfg_b).orchestrator(client)).run(demo)
    assert not res.errors and res.evaluation.exact_recommendation == 13
    # 13 chamados × até 5 tarefas em sequência viram poucas rodadas de lote, não 50+ requisições soltas
    assert 3 <= len(res.api_batches) <= 8, res.api_batches
    assert sum(len(v) for v in server.batches.values()) == server.requests
    ch = res.assessments[0].llm_calls[0]
    assert ch.via_batch and ch.batch_id
    sync = CostCalculator(cfg_b).price(ch.model)
    assert ch.cost_usd < (ch.input_tokens * sync.input + ch.output_tokens * sync.output) / 1e6  # desconto aplicado


class FakeIaraClient:
    """Cliente IARA falso (chat.completions no formato OpenAI) respondendo a partir do gabarito."""

    def __init__(self, cfg):
        self.server = FakeServer(cfg)
        self.models: set[str] = set()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw) -> dict:
        self.server.requests += 1
        self.models.add(kw["model"])
        fmt = kw["response_format"]
        assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
        schema = fmt["json_schema"]["schema"]
        assert schema["additionalProperties"] is False and schema["required"] == list(schema["properties"])
        system, user = kw["messages"]
        assert system["role"] == "system" and user["role"] == "user"
        self.server.images += sum(b["type"] == "image_url" for b in user["content"])
        out = self.server.answer(schema, " ".join(b["text"] for b in user["content"] if b["type"] == "text"))
        return {
            "id": "chatcmpl-mock",
            "model": f"{kw['model']}-2025-04-14",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 200}},
        }


def test_iara_runs_the_same_pipeline_in_sync_and_batch_mode(cfg, demo):
    """Trocar para a IARA é só configuração: mesmo pipeline e mesmo resultado; no modo lote cai para chamadas síncronas."""
    for kind, client_cls in ((BatchMode.SYNC, ProviderClient), (BatchMode.BATCH, BatchClient)):
        fake = FakeIaraClient(cfg)
        c = cfg.with_overrides(**{"execution.mode": Mode.API, "batch.kind": kind, "models.main": "iara:gpt-4.1", "models.fast": "iara:gpt-4.1-mini"})
        client = client_cls(c, {"iara": IaraProvider(client=fake)})
        res = BatchRunner(c, ComponentFactory(c).orchestrator(client)).run(demo)
        assert not res.errors and res.evaluation.exact_recommendation == 13
        assert fake.models == {"gpt-4.1", "gpt-4.1-mini"} and fake.server.images > 30 and not res.api_batches
        call = res.assessments[0].llm_calls[0]
        assert call.provider == "iara" and call.model.startswith("iara:gpt-4.1") and call.resolved_model.endswith("-2025-04-14")
        assert (call.input_tokens, call.output_tokens, call.cache_read_tokens) == (800, 100, 200)
        assert not call.via_batch and call.cost_usd > 0


def _wait(c: TestClient, ex_id: str) -> dict:
    # até 60 s: com cache vazio, a 1ª execução monta o índice de hashes de todas as fotos (~20 s com os 113 chamados)
    for _ in range(600):
        e = c.get(f"/api/runs/{ex_id}").json()
        if e["status"] == "completed":
            return e
        time.sleep(0.1)
    raise AssertionError("execução não terminou")


def test_api_run_feedback_upload_and_metrics(cfg):
    c = TestClient(create_app(cfg))
    e = _wait(c, c.post("/api/runs", json={"tickets": ["00482193", "00523310"], "mode": "simulated"}).json()["id"])
    assert e["evaluation"]["exact_recommendation"] == 2
    assessment = e["tickets"]["00482193"]["assessment"]
    assert assessment["amount_at_issue"] == 3382.5

    # persistência: uma app nova (como após reiniciar) lê a execução e o último parecer do banco
    c2 = TestClient(create_app(cfg))
    assert c2.get(f"/api/runs/{e['id']}").json()["tickets"]["00482193"]["assessment"]["score"] == 72  # v9: 3 de 6 fotos fora do escopo
    last = next(x for x in c2.get("/api/tickets").json() if x["ticket_id"] == "00482193")["last"]
    assert last["assessment_id"] == assessment["record_id"]

    r = c2.post(
        f"/api/assessments/{assessment['record_id']}/feedback",
        json={"action": "adjust", "unfounded_findings": ["missing_before_photo"], "comment": "não exigido"},
    )
    assert r.status_code == 201
    m = c2.get("/api/metrics").json()
    assert m["unfounded_findings"] == [{"kind": "missing_before_photo", "n": 1}]

    spreadsheet = load_ticket_spreadsheet(cfg)
    photo = next((cfg.tickets_dir / "00534519" / "attachments").glob("IMG_*.jpg")).read_bytes()
    form = {
        "workstream": "SETA",
        "category": "electrical",
        "symptom": "electrical_failure",
        "maintenance_type": "corrective",
        "moment": "execution",
        "scope": "Trocar tomadas queimadas",
        "branch_name": "Ag. Teste",
    }
    r = c2.post("/api/tickets", data=form, files=[("spreadsheet", ("quote.xlsx", spreadsheet)), ("attachments", ("a.jpg", photo, "image/jpeg"))])
    assert r.status_code == 201 and r.json()["origin"] == "upload"
    new = r.json()["ticket_id"]
    model = c2.get("/api/spreadsheet-template").content
    assert c2.post("/api/tickets", data=form, files=[("spreadsheet", ("m.xlsx", model))]).status_code == 422
    assert c2.delete("/api/tickets/00482193").status_code == 403
    assert c2.delete(f"/api/tickets/{new}").status_code == 204


def load_ticket_spreadsheet(cfg) -> bytes:
    return next((cfg.tickets_dir / "00534519" / "attachments").glob("*.xlsx")).read_bytes()
