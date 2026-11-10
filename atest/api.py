"""API do painel web (FastAPI). Também serve o front-end compilado (panel/dist).

Chamados      GET /api/tickets · GET /api/tickets/{id} · GET /api/tickets/{id}/attachments/{name}
              POST /api/tickets (upload) · DELETE /api/tickets/{id} (só enviados pelo painel)
              GET /api/tickets/{id}/history · GET /api/tickets/{id}/reuse · GET /api/spreadsheet-template
Execuções     POST /api/runs · GET /api/runs · GET /api/runs/{id}
Pareceres     GET /api/assessments/{id} · GET|POST /api/assessments/{id}/feedback
Operação      GET /api/config · GET /api/metrics
Portal        POST /api/admin/login · GET /api/admin/overview · PUT /api/admin/config/{seção} · usuários, histórico e limpeza de análises (com token)
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

from . import providers
from .admin import SECTIONS, AdminError, AdminStore
from .attachments import compute_hashes, detail_level, distance, exif_date, hashes_with_crops
from .batch import BatchRunner, ComponentFactory, new_run_id
from .config import KEY_ENV_VAR, ROOT, BatchMode, Mode, Settings, has_credentials, missing_keys, used_providers
from .database import Database, Feedback, FeedbackInput
from .domain import (
    CATEGORY_LABEL,
    SYMPTOM_LABEL,
    Assessment,
    Attachment,
    Category,
    MaintenanceType,
    Moment,
    Quote,
    Stage,
    Symptom,
    Ticket,
    Workstream,
)
from .evaluation import Evaluation, GroundTruthEvaluator, TicketComparison
from .formatting import error_message, pt_validation_error
from .observability import configure_logging, event
from .repository import QuoteError, References, list_tickets, load_ground_truth, load_ticket, read_quote
from .scenarios import catalog as scenario_catalog
from .scenarios import tags_for
from .spreadsheet import spreadsheet_template
from .validation import DatasetCatalog

log = logging.getLogger(__name__)
DIST = ROOT / "panel" / "dist"
ATTACHMENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".pdf": "application/pdf"}


# ============================================================================ contratos
class Expected(BaseModel):
    """Gabarito resumido de um chamado, para comparação na tela."""

    recommendation: str
    score: int | None
    findings: list[str]
    optional: list[str]
    missing: list[str]


class LastAssessment(BaseModel):
    """Último parecer gravado do chamado (lista da Análise)."""

    assessment_id: int
    run_id: str | None
    generated_at: str
    recommendation: str
    score: int | None
    mode: str
    feedback: str | None


class TicketSummary(BaseModel):
    """Linha da lista de chamados do painel."""

    ticket_id: str
    origin: str
    dataset: str
    workstream: str
    category: str
    category_label: str
    symptom: str
    symptom_label: str
    scope: str
    branch: str
    environment: str
    supplier: str
    quoted_value: float | None
    moment: str
    maintenance_type: str
    n_photos: int
    expected: Expected | None
    last: LastAssessment | None
    tags: list[str] = []  # cenários de teste que o gabarito descreve (atest/scenarios.py)
    scenario: dict[str, str] | None = None  # catálogo de cenários (0300…): id, título e o que testa


class AttachmentInfo(BaseModel):
    """Anexo com a URL para abrir no painel."""

    index: int
    name: str
    content_type: str
    url: str
    is_image: bool


class TicketDetail(TicketSummary):
    """Chamado completo para a aba Entrada: dados, anexos, orçamento lido e histórico."""

    dates: dict[str, str | None]
    quote: Quote | None
    quote_error: str | None
    attachments: list[AttachmentInfo]


class PhotoFacts(BaseModel):
    """Metadados de uma foto: quando foi tirada (EXIF), quando foi enviada, tamanho e nível de detalhe."""

    file: str
    url: str
    taken_at: datetime | None = Field(None, description="data e hora do EXIF (DateTimeOriginal)")
    uploaded_on: date | None = None
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    detail: float | None = None


class TicketFacts(BaseModel):
    """Dados de um chamado para comparar com outro (agência, fornecedor, datas, situação)."""

    ticket_id: str
    source: Literal["tickets", "history"]
    workstream: str
    category_label: str
    symptom_label: str
    scope: str
    branch_code: str
    branch_name: str
    environment: str
    supplier_name: str
    supplier_cnpj: str
    quoted_value: float | None
    opening: date
    supplier_submission: date
    manager_review: date | None
    status: str
    n_photos: int
    last_recommendation: str | None = None
    last_score: int | None = None


class ReuseComparison(BaseModel):
    """Foto reaproveitada: o chamado atual, o chamado de origem, as duas fotos e a checagem de ordem no tempo."""

    current: TicketFacts
    current_photo: PhotoFacts
    origin: TicketFacts
    origin_photo: PhotoFacts
    distance: int | None = Field(None, description="phash + dhash (0 = idênticas), comparando também com recortes da original")
    limit: int
    basis: Literal["exif", "mixed", "dates"] = Field(description="exif: data/hora das duas fotos; mixed: só uma tem EXIF; dates: só datas de envio")
    origin_moment: datetime
    current_moment: datetime
    chronology_ok: bool = Field(description="a origem é anterior ou igual ao chamado atual")
    gap_hours: float
    same_branch: bool
    same_supplier: bool


class RunRequest(BaseModel):
    """Pedido de execução vindo do painel (chamados escolhidos ou conjunto + amostra)."""

    tickets: list[str] = Field(default_factory=list, description="ids; ou use conjunto (+ amostra)")
    dataset: str | None = Field(None, description="demonstracao | validacao | enviados | todos")
    sample: int | None = Field(None, ge=1, description="amostra aleatória (reprodutível) do conjunto")
    simulated_noise: float = Field(0.0, ge=0, le=0.6, description="só no modo simulado")
    label: str = ""
    mode: Mode = Mode.SIMULATED
    phase: int = Field(2, ge=1, le=2)
    batch_mode: BatchMode = BatchMode.SYNC
    main_model: str | None = None
    fast_model: str | None = None
    provider: str | None = Field(None, description="provedor escolhido no painel (um de panel.providers); sem ele, vale a configuração")
    refresh: bool = Field(False, description="executa o agente de novo, sem reaproveitar respostas do modelo salvas no cache em disco")


class TicketState(BaseModel):
    """Progresso de um chamado dentro de uma execução."""

    ticket_id: str
    status: Literal["queue", "running", "done", "error"] = "queue"
    stage: Stage | None = None
    completed_stages: list[Stage] = Field(default_factory=list)
    assessment: Assessment | None = None
    recommendation: str | None = None
    score: int | None = None
    comparison: TicketComparison | None = None
    error: str | None = None


class Run(BaseModel):
    """Execução em andamento ou concluída, como o painel acompanha."""

    id: str
    created_at: datetime
    completed_at: datetime | None = None
    status: Literal["running", "completed"] = "running"
    mode: Mode
    batch_mode: BatchMode
    phase: int
    models: dict[str, str]
    tickets: dict[str, TicketState]
    evaluation: Evaluation | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_brl: float = 0.0
    api_batches: list[str] = Field(default_factory=list)
    output_folder: str | None = None
    label: str = ""
    signature: str = ""
    simulated_noise: float = 0.0
    has_validation: bool = False


class Option(BaseModel):
    """Valor e rótulo de um campo de escolha (categoria, sintoma)."""

    value: str
    label: str


class LoginInput(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=200)


class SaveSectionInput(BaseModel):
    data: dict | None = None
    comment: str = Field("", max_length=500)


class NewUserInput(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=200)


class PasswordInput(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class DeleteAssessmentsInput(BaseModel):
    """Limpeza do histórico de análises: os pareceres escolhidos ou todos."""

    ids: list[int] = Field(default_factory=list, max_length=100_000)
    all: bool = Field(False, description="apaga todos os pareceres (ignora ids)")


# Suba quando o painel passar a depender de rotas ou campos novos da API (panel/src/api.ts: PANEL_API).
PANEL_API = 6


class ProviderChoice(BaseModel):
    """Provedor do seletor do painel (config: [panel.providers]), com os modelos que ele preenche."""

    id: str
    label: str
    main: str = Field(description='"provedor:modelo" principal')
    fast: str
    available: bool = Field(description="há credencial no ambiente")
    credentials: list[str] = Field(default_factory=list, description="variáveis de ambiente que o provedor exige (só os nomes)")


def provider_choices(cfg: Settings) -> list[ProviderChoice]:
    """Provedores do seletor: o de [models].main (sempre, primeiro, com os modelos de [models]) e os ativos de panel.providers."""
    default = cfg.llm.default_provider

    def full(m: str) -> str:
        return m if ":" in m else f"{default}:{m}"

    def choice(name: str, label: str, main: str, fast: str) -> ProviderChoice:
        return ProviderChoice(
            id=name, label=label or name, main=main, fast=fast, available=has_credentials(name), credentials=list(KEY_ENV_VAR.get(name, ()))
        )

    main, fast = full(cfg.models.main), full(cfg.models.fast)
    current = providers.split_model(main, default)[0]
    p = cfg.panel.providers.get(current)
    fast_same = providers.split_model(fast, default)[0] == current
    out = {current: choice(current, p.label if p else "", main, fast if fast_same else (p.fast if p else main))}
    for name, p in cfg.panel.providers.items():
        if p.enabled and name not in out:
            out[name] = choice(name, p.label, p.main, p.fast)
    return list(out.values())


class ModelOption(BaseModel):
    """Modelo conhecido pela configuração: da tabela de preços ou já usado em models.*."""

    id: str = Field(description='"provedor:modelo", como vai para models.main / models.fast')
    provider: str
    name: str
    input_price: float | None = Field(None, description="USD por milhão de tokens de entrada")
    output_price: float | None = None
    detail: str = Field("", description="complemento mostrado no painel, ex.: o backend da IARA")
    text_only: bool = Field(False, description="não lê imagens: falha nas tarefas com fotos e anexos")


class AppSettings(BaseModel):
    """Configuração exposta ao painel (modelos, provedores, chaves faltando, limites do portão)."""

    environment: str
    version: str
    api_available: bool
    main_model: str
    fast_model: str
    phase: int
    batch_mode: str
    rubric_version: str
    prompts_version: str
    usd_brl_rate: float
    categories: list[Option]
    symptoms: list[Option]
    providers: list[str]
    missing_keys: list[str]
    signature: str
    validation: dict
    rubric: dict = {}  # pesos, descontos por severidade, faixas e confiança: o painel explica o score com eles
    models: list[ModelOption] = []  # sugestões para os campos de modelo (a pessoa pode digitar outro)
    keyed_providers: list[str] = []  # provedores com chave de API no ambiente (só os nomes, nunca a chave)
    provider_choices: list[ProviderChoice] = []  # seletor de provedor do painel (o primeiro é o da configuração)
    panel_api: int = PANEL_API  # revisão do contrato com o painel: front-end mais novo que o servidor avisa para reiniciar


class Dataset(BaseModel):
    """Conjunto de chamados disponível (demonstração, validação, enviados)."""

    name: str
    label: str
    n: int


# ============================================================================ execuções em segundo plano
class RunManager:
    """Dispara execuções em segundo plano e guarda o progresso em memória (com fallback para o banco)."""

    def __init__(self, cfg_base: Settings, database: Database):
        self.cfg_base = cfg_base
        self.database = database
        self.runs: dict[str, Run] = {}
        self.lock = threading.Lock()

    def resolve_ids(self, request: RunRequest) -> list[str]:
        """Chamados da execução: os escolhidos na tela ou uma amostra reprodutível de um conjunto."""
        if request.tickets:
            return request.tickets
        catalog = DatasetCatalog(self.cfg_base)
        ids = catalog.sample(catalog.ids(request.dataset or "all"), request.sample)
        if not ids:
            raise HTTPException(422, "Nenhum chamado no conjunto escolhido.")
        return ids

    def run_settings(self, request: RunRequest) -> Settings:
        """Configuração da execução: a base com modo, fase, envio, provedor e modelos escolhidos no painel."""
        base = self.cfg_base
        overrides: dict = {
            "validation.simulated_noise": request.simulated_noise if request.mode == Mode.SIMULATED else 0.0,
            "execution.mode": request.mode,
            "pipeline.phase": request.phase,
            "batch.kind": request.batch_mode,
            "models.main": request.main_model or base.models.main,
            "models.fast": request.fast_model or base.models.fast,
            "llm.refresh_cache": request.refresh,
        }
        if request.provider:
            choice = next((c for c in provider_choices(base) if c.id == request.provider), None)
            if choice is None:
                raise HTTPException(422, f"Provedor '{request.provider}' não está em panel.providers (config/settings.toml).")
            overrides["models.main"] = request.main_model or choice.main
            overrides["models.fast"] = request.fast_model or choice.fast

            # tarefas e contingência configuradas para outro provedor não valem quando a pessoa escolhe um provedor
            def same(m: str) -> bool:
                return providers.split_model(m, base.llm.default_provider)[0] == choice.id

            overrides["models.tasks"] = {k: m for k, m in base.models.tasks.items() if same(m)}
            overrides["models.fallback"] = {k: m for k, m in base.models.fallback.items() if same(m)}
        cfg = base.with_overrides(**overrides)
        if cfg.execution.mode == Mode.API and (missing := missing_keys(cfg)):
            raise HTTPException(
                400, f"Modo API sem credencial para: {', '.join(missing)}. Preencha config/.secrets.toml ou as variáveis de ambiente."
            )
        return cfg

    def start(self, request: RunRequest) -> Run:
        """Valida o pedido, cria a execução e roda em uma thread; devolve o estado inicial."""
        ids = self.resolve_ids(request)
        cfg = self.run_settings(request)
        batch_mode = request.batch_mode if request.mode == Mode.API else BatchMode.SYNC
        ex = Run(
            id=new_run_id(),
            created_at=datetime.now(),
            mode=request.mode,
            batch_mode=batch_mode,
            phase=request.phase,
            models={"main": cfg.models.main, "fast": cfg.models.fast},
            tickets={c: TicketState(ticket_id=c) for c in sorted(ids)},
            label=request.label,
            signature=cfg.signature(),
            simulated_noise=cfg.validation.simulated_noise,
        )
        with self.lock:
            self.runs[ex.id] = ex
        threading.Thread(target=self._run, args=(ex, cfg, ids), daemon=True).start()
        return ex

    def _run(self, ex: Run, cfg: Settings, ids: list[str]) -> None:
        def on_progress(tid: str, stage: Stage) -> None:
            with self.lock:
                st = ex.tickets[tid]
                if st.stage and st.stage not in st.completed_stages:
                    st.completed_stages.append(st.stage)
                st.status, st.stage = "running", stage

        def on_complete(tid: str, assessment: Assessment | None, error: str | None) -> None:
            with self.lock:
                st = ex.tickets[tid]
                if assessment:
                    st.status, st.assessment, st.stage = "done", assessment, Stage.DONE
                    st.recommendation, st.score = assessment.recommendation.value, assessment.score
                    st.comparison = GroundTruthEvaluator(cfg.ground_truth_dir).compare(assessment)
                else:
                    st.status, st.error = "error", error

        try:
            res = BatchRunner(cfg, ComponentFactory(cfg).orchestrator(), self.database).run(
                ids,
                run_id=ex.id,
                on_progress=on_progress,
                on_complete=on_complete,
                label=ex.label,
            )
            with self.lock:
                ex.evaluation = res.evaluation
                ex.has_validation = res.validation is not None
                ex.input_tokens, ex.output_tokens = res.tokens
                ex.cost_usd = res.cost_usd
                ex.cost_brl = round(res.cost_usd * cfg.costs.usd_brl_rate, 4)
                ex.api_batches = res.api_batches
                ex.output_folder = str(res.output_folder.relative_to(ROOT)) if res.output_folder else None
        except Exception as e:
            log.exception("execução %s falhou", ex.id)
            with self.lock:
                for st in ex.tickets.values():
                    if st.status in ("queue", "running"):
                        st.status, st.error = "error", error_message(e)
        finally:
            with self.lock:
                ex.status, ex.completed_at = "completed", datetime.now()

    def get(self, ex_id: str, light: bool = False) -> Run:
        """Estado da execução: da memória (em andamento) ou do banco (execuções anteriores)."""
        with self.lock:
            if ex_id in self.runs:
                ex = self.runs[ex_id]
                if light:  # progresso sem os pareceres completos (lotes grandes)
                    return ex.model_copy(update={"tickets": {k: v.model_copy(update={"assessment": None}) for k, v in ex.tickets.items()}})
                return ex.model_copy(deep=True)
        return self._from_db(ex_id, light)

    def _from_db(self, ex_id: str, light: bool = False) -> Run:
        row = next((e for e in self.database.list_runs(500) if e["id"] == ex_id), None)
        if row is None:
            raise HTTPException(404, "execução não encontrada")
        states = {}
        for p in self.database.run_assessments(ex_id):
            states[p.ticket_id] = TicketState(
                ticket_id=p.ticket_id,
                status="done",
                stage=Stage.DONE,
                assessment=None if light else p,
                recommendation=p.recommendation.value,
                score=p.score,
                comparison=GroundTruthEvaluator(self.cfg_base.ground_truth_dir).compare(p),
            )
        for tid, error in (row["errors"] or {}).items():
            states[tid] = TicketState(ticket_id=tid, status="error", error=error)
        return Run(
            id=ex_id,
            created_at=row["created_at"],
            completed_at=row["completed_at"],
            status="completed" if row["status"] == "completed" else "running",
            mode=row["mode"],
            batch_mode=row["batch_mode"],
            phase=row["phase"],
            models=row["models"],
            tickets=states,
            evaluation=row["evaluation"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            cost_usd=row["cost_usd"],
            cost_brl=row["cost_brl"],
            api_batches=row["batches"] or [],
            output_folder=row["output_folder"],
            label=row.get("label") or "",
            signature=row.get("signature") or "",
            has_validation=row.get("validation") is not None,
        )


# ============================================================================ app
def create_app(cfg: Settings) -> FastAPI:
    """Cria a aplicação FastAPI do painel: API em /api e front-end compilado na raiz."""
    configure_logging(cfg)
    database = Database(cfg.database_file)
    admin = AdminStore(database, cfg.admin)
    base_cfg = cfg  # o que está nos TOML; a configuração efetiva fica em manager.cfg_base
    manager = RunManager(admin.apply(base_cfg), database)
    app = FastAPI(title="Atest.AI", version=cfg.version)

    def summary(folder: Path) -> TicketSummary:
        ch = load_ticket(folder)
        d = ch.data
        g = load_ground_truth(cfg.ground_truth_dir, ch.id)
        hist = database.ticket_history(ch.id)
        last = (
            LastAssessment(
                assessment_id=hist[0]["id"],
                run_id=hist[0]["run_id"],
                generated_at=hist[0]["generated_at"],
                recommendation=hist[0]["recommendation"],
                score=hist[0]["score"],
                mode=hist[0]["mode"],
                feedback=hist[0]["feedback"],
            )
            if hist
            else None
        )
        return TicketSummary(
            ticket_id=ch.id,
            origin=d.origin,
            dataset=d.dataset,
            workstream=d.workstream.value,
            category=d.category.value,
            category_label=d.category.label,
            symptom=d.symptom.value,
            symptom_label=d.symptom.label,
            scope=d.requested_scope,
            branch=d.branch.name,
            environment=d.branch.environment,
            supplier=d.supplier.name,
            quoted_value=d.quoted_value,
            moment=d.moment.value,
            maintenance_type=d.maintenance_type.value,
            n_photos=sum(a.is_image for a in ch.attachments),
            last=last,
            expected=Expected(recommendation=g.recommendation.value, score=g.score, findings=g.findings, optional=g.optional, missing=g.missing)
            if g
            else None,
            tags=tags_for(g, manager.cfg_base.rubric),
            scenario=g.scenario if g else None,
        )

    def attachment_info(tid: str, a: Attachment) -> AttachmentInfo:
        return AttachmentInfo(
            index=a.index, name=a.name, content_type=a.content_type, is_image=a.is_image, url=f"/api/tickets/{tid}/attachments/{a.name}"
        )

    def folder_of(tid: str) -> Path:
        folder = (cfg.tickets_dir / tid).resolve()
        if not folder.is_relative_to(cfg.tickets_dir.resolve()) or not (folder / "ticket.json").exists():
            raise HTTPException(404, "chamado não encontrado")
        return folder

    def model_options() -> list[ModelOption]:
        """Modelos da tabela de preços + os já configurados, sem repetir, com o provedor explícito."""
        default = cfg.llm.default_provider

        def full(m: str) -> str:
            return m if ":" in m else f"{default}:{m}"

        ids = [full(m) for m in cfg.costs.prices]
        ids += [full(m) for m in [cfg.models.main, cfg.models.fast, *cfg.models.tasks.values(), *cfg.models.fallback.values()] if m]
        ids += [m for c in provider_choices(cfg) for m in (c.main, c.fast)]
        # catálogo de um provedor ([llm.provider_options.<p>.models] = {grupo: [modelos]}, ex.: backends da IARA)
        detail: dict[str, str] = {}
        text_only: set[str] = set()
        for prov, opts in cfg.llm.provider_options.items():
            for group, names in (opts.get("models") or {}).items():
                for name in names:
                    ids.append(f"{prov}:{name}")
                    detail.setdefault(f"{prov}:{name}", group)
            text_only |= {f"{prov}:{name}" for name in opts.get("text_only") or ()}
        out = []
        for mid in dict.fromkeys(ids):
            provider, name = mid.split(":", 1)
            price = cfg.costs.prices.get(name) or cfg.costs.prices.get(mid)
            out.append(
                ModelOption(
                    id=mid,
                    provider=provider,
                    name=name,
                    input_price=price.input if price else None,
                    output_price=price.output if price else None,
                    detail=detail.get(mid, ""),
                    text_only=mid in text_only,
                )
            )
        return out


    # ------------------------------------------------------------------ portal de configuração (com login)
    @app.exception_handler(AdminError)
    def admin_error(_: Request, e: AdminError) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=e.status)

    def admin_user(authorization: str | None) -> str:
        token = authorization.removeprefix("Bearer ").strip() if authorization else None
        user = admin.user_for(token)
        if not user:
            raise HTTPException(401, "Sessão expirada ou inválida. Entre de novo.")
        return user

    def overview() -> dict:
        eff = manager.cfg_base
        counts_cat: dict[str, int] = {}
        counts_sym: dict[str, int] = {}
        pairs: dict[str, set[str]] = {}
        total = 0
        for folder in list_tickets(cfg.tickets_dir):
            d = load_ticket(folder).data
            total += 1
            counts_cat[d.category.value] = counts_cat.get(d.category.value, 0) + 1
            counts_sym[d.symptom.value] = counts_sym.get(d.symptom.value, 0) + 1
            pairs.setdefault(d.category.value, set()).add(d.symptom.value)
        sections = {}
        for sec in SECTIONS:
            latest = admin.latest(sec)
            sections[sec] = {
                "data": admin.section_data(sec, base_cfg),
                "base": admin.base_data(sec, base_cfg),
                "overridden": bool(latest and latest["data"] is not None),
                "version_id": latest["id"] if latest else None,
            }
        lpu = References(base_cfg).lpu
        return {
            "sections": sections,
            "catalog": {
                "categories": [{"value": c.value, "label": CATEGORY_LABEL[c], "tickets": counts_cat.get(c.value, 0),
                                "symptoms_seen": sorted(pairs.get(c.value, set()))} for c in Category],
                "symptoms": [{"value": sy.value, "label": SYMPTOM_LABEL[sy], "tickets": counts_sym.get(sy.value, 0)} for sy in Symptom],
                "tickets": total,
            },
            "lpu": {ws: [i.model_dump() for i in items.values()] for ws, items in lpu.items()},
            "system": {
                "rubric_version": eff.rubric.version, "prompts_version": cfg.prompts.version,
                "signature": eff.signature(), "base_signature": base_cfg.signature(),
                "main_model": cfg.models.main, "fast_model": cfg.models.fast, "phase": cfg.pipeline.phase,
                "validation": cfg.validation.model_dump(), "environment": cfg.environment, "version": cfg.version,
            },
        }

    @app.post("/api/admin/login")
    def admin_login(body: LoginInput) -> dict:
        token, expires = admin.login(body.username, body.password)
        event("admin_login", user=body.username.strip().lower())
        return {"token": token, "username": body.username.strip().lower(), "expires_at": expires.isoformat(timespec="seconds")}

    @app.post("/api/admin/logout", status_code=204)
    def admin_logout(authorization: Annotated[str | None, Header()] = None) -> Response:
        admin_user(authorization)
        admin.logout(authorization.removeprefix("Bearer ").strip())  # type: ignore[union-attr]
        return Response(status_code=204)

    @app.get("/api/admin/me")
    def admin_me(authorization: Annotated[str | None, Header()] = None) -> dict:
        return {"username": admin_user(authorization)}

    @app.get("/api/admin/overview")
    def admin_overview(authorization: Annotated[str | None, Header()] = None) -> dict:
        admin_user(authorization)
        return overview()

    def apply_and_overview(vid: int, user: str, section: str) -> dict:
        manager.cfg_base = admin.apply(base_cfg)
        event("admin_config_saved", user=user, section=section, version_id=vid, signature=manager.cfg_base.signature())
        return overview()

    @app.put("/api/admin/config/{section}")
    def admin_save(section: Literal["rubric", "checklists"], body: SaveSectionInput, authorization: Annotated[str | None, Header()] = None) -> dict:
        user = admin_user(authorization)
        if body.data is None:
            raise HTTPException(422, "Envie a seção completa em 'data'.")
        vid = admin.save(section, body.data, base_cfg, user, body.comment)
        return apply_and_overview(vid, user, section)

    @app.post("/api/admin/config/{section}/reset")
    def admin_reset(section: Literal["rubric", "checklists"], body: SaveSectionInput, authorization: Annotated[str | None, Header()] = None) -> dict:
        user = admin_user(authorization)
        vid = admin.save(section, None, base_cfg, user, body.comment)
        return apply_and_overview(vid, user, section)

    @app.post("/api/admin/history/{vid}/restore")
    def admin_restore(vid: int, body: SaveSectionInput, authorization: Annotated[str | None, Header()] = None) -> dict:
        user = admin_user(authorization)
        old = admin.version(vid)
        comment = body.comment or f"Restaurou a versão #{vid}"
        new = admin.save(old["section"], old["data"], base_cfg, user, comment)
        return apply_and_overview(new, user, old["section"])

    @app.get("/api/admin/history")
    def admin_history(authorization: Annotated[str | None, Header()] = None) -> list[dict]:
        admin_user(authorization)
        return admin.history()

    @app.get("/api/admin/assessments")
    def admin_assessments(authorization: Annotated[str | None, Header()] = None) -> list[dict]:
        admin_user(authorization)
        return database.list_assessments()

    @app.post("/api/admin/assessments/delete")
    def admin_delete_assessments(body: DeleteAssessmentsInput, authorization: Annotated[str | None, Header()] = None) -> dict:
        """Limpa o histórico de análises: pareceres, feedbacks e chamadas ao modelo; execuções vazias saem junto."""
        user = admin_user(authorization)
        if not body.all and not body.ids:
            raise HTTPException(422, "Escolha ao menos uma análise para apagar.")
        result = database.delete_assessments(None if body.all else body.ids)
        with manager.lock:  # execuções concluídas guardadas em memória passam a ser lidas do banco (já sem os pareceres)
            for rid in result["runs_touched"]:
                if (ex := manager.runs.get(rid)) and ex.status == "completed":
                    del manager.runs[rid]
        event("admin_assessments_deleted", user=user, all=body.all, assessments=result["assessments"], runs=len(result["runs_removed"]))
        return result

    @app.get("/api/admin/users")
    def admin_users(authorization: Annotated[str | None, Header()] = None) -> list[dict]:
        admin_user(authorization)
        return admin.users()

    @app.post("/api/admin/users", status_code=201)
    def admin_add_user(body: NewUserInput, authorization: Annotated[str | None, Header()] = None) -> list[dict]:
        user = admin_user(authorization)
        admin.add_user(body.username, body.password, user)
        event("admin_user_created", user=user, new_user=body.username.strip().lower())
        return admin.users()

    @app.post("/api/admin/password", status_code=204)
    def admin_password(body: PasswordInput, authorization: Annotated[str | None, Header()] = None) -> Response:
        user = admin_user(authorization)
        admin.change_password(user, body.current, body.new)
        event("admin_password_changed", user=user)
        return Response(status_code=204)

    # ------------------------------------------------------------------ configuração e métricas
    @app.get("/api/config")
    def config() -> AppSettings:
        return AppSettings(
            environment=cfg.environment,
            version=cfg.version,
            api_available=any(c.available for c in provider_choices(cfg)),
            main_model=cfg.models.main,
            fast_model=cfg.models.fast,
            phase=cfg.pipeline.phase,
            batch_mode=cfg.batch.kind.value,
            rubric_version=manager.cfg_base.rubric.version,
            prompts_version=cfg.prompts.version,
            usd_brl_rate=cfg.costs.usd_brl_rate,
            categories=[Option(value=c.value, label=CATEGORY_LABEL[c]) for c in Category],
            symptoms=[Option(value=s.value, label=SYMPTOM_LABEL[s]) for s in Symptom],
            providers=sorted(used_providers(cfg)),
            missing_keys=missing_keys(cfg),
            signature=manager.cfg_base.signature(),
            validation=cfg.validation.model_dump(),
            rubric={
                **manager.cfg_base.rubric.model_dump(mode="json", include={"weights", "discount_by_severity", "bands", "confidence"}),
                "absorbs": {k: t.absorbs for k, t in manager.cfg_base.rubric.finding_types.items() if t.absorbs},
            },
            models=model_options(),
            keyed_providers=sorted(p for p in KEY_ENV_VAR if has_credentials(p)),
            provider_choices=provider_choices(cfg),
        )

    @app.get("/api/datasets")
    def datasets() -> list[Dataset]:
        labels = {
            "demo": "Demonstração (casos do deck)",
            "validation": "Validação (defeitos injetados)",
            "itau": "Itaú",
            "scenarios": "Cenários de teste (um por tipo de problema)",
            "uploaded": "Enviados pelo painel",
        }
        counts = DatasetCatalog(cfg).counts()
        found = [Dataset(name=k, label=labels.get(k, k), n=v) for k, v in sorted(counts.items())]
        return [*found, Dataset(name="all", label="Todos", n=sum(counts.values()))]

    @app.get("/api/scenarios")
    def scenarios() -> list[dict[str, str]]:
        """Tipos de cenário de teste, na ordem de exibição; cada chamado traz os seus em `tags`."""
        return scenario_catalog()

    @app.get("/api/metrics")
    def metrics() -> dict:
        return database.metrics()

    # ------------------------------------------------------------------ chamados
    @app.get("/api/tickets")
    def tickets() -> list[TicketSummary]:
        return [summary(p) for p in list_tickets(cfg.tickets_dir)]

    @app.get("/api/tickets/{tid}")
    def ticket(tid: str) -> TicketDetail:
        folder = folder_of(tid)
        ch = load_ticket(folder)
        quote, error = None, None
        if ch.spreadsheets:
            try:
                quote = read_quote(ch.spreadsheets[0].path)
            except QuoteError as e:
                error = str(e)
        else:
            error = "sem planilha de orçamento"
        dates = {k: (v.isoformat() if v else None) for k, v in ch.data.dates.model_dump().items()}
        return TicketDetail(
            **summary(folder).model_dump(), dates=dates, quote=quote, quote_error=error, attachments=[attachment_info(tid, a) for a in ch.attachments]
        )

    @app.get("/api/tickets/{tid}/history")
    def ticket_history(tid: str) -> list[dict]:
        return database.ticket_history(tid)

    def any_folder(tid: str) -> tuple[Path, Literal["tickets", "history"]]:
        """Pasta do chamado entre os atuais e o histórico (onde ficam os chamados antigos usados na checagem de integridade)."""
        if not tid.isdigit() or len(tid) != 8:
            raise HTTPException(404, f"chamado {tid} não encontrado")
        for base, source in ((cfg.tickets_dir, "tickets"), (cfg.history_dir, "history")):
            folder = (base / tid).resolve()
            if folder.is_relative_to(base.resolve()) and (folder / "ticket.json").exists():
                return folder, source  # type: ignore[return-value]
        raise HTTPException(404, f"chamado {tid} não encontrado")

    def ticket_facts(tid: str) -> tuple[TicketFacts, Path]:
        folder, source = any_folder(tid)
        ch = load_ticket(folder)
        d = ch.data
        hist = database.ticket_history(tid)
        facts = TicketFacts(
            ticket_id=d.ticket_id, source=source, workstream=d.workstream.value,
            category_label=d.category.label, symptom_label=d.symptom.label, scope=d.requested_scope,
            branch_code=d.branch.code, branch_name=d.branch.name, environment=d.branch.environment,
            supplier_name=d.supplier.name, supplier_cnpj=d.supplier.cnpj, quoted_value=d.quoted_value,
            opening=d.dates.opening, supplier_submission=d.dates.supplier_submission, manager_review=d.dates.manager_review,
            status=d.status, n_photos=sum(a.is_image for a in ch.attachments),
            last_recommendation=hist[0]["recommendation"] if hist else None, last_score=hist[0]["score"] if hist else None,
        )
        return facts, folder

    def photo_facts(tid: str, folder: Path, name: str) -> tuple[PhotoFacts, Path]:
        base = (folder / "attachments").resolve()
        path = (base / name).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise HTTPException(404, f"foto {name} não encontrada no chamado {tid}")
        meta = next((a for a in load_ticket(folder).data.attachments if a.file_name == name), None)
        try:
            with Image.open(path) as img:
                w, h = img.size
            detail = round(detail_level(path), 1)
        except OSError as e:  # inclui arquivo que não é imagem
            raise HTTPException(422, f"{name} não é uma imagem legível") from e
        return PhotoFacts(
            file=name, url=f"/api/tickets/{tid}/attachments/{name}", taken_at=exif_date(path),
            uploaded_on=meta.data_upload if meta else None, size_bytes=path.stat().st_size,
            width=w, height=h, detail=detail,
        ), path

    @app.get("/api/tickets/{tid}/reuse")
    def photo_reuse(tid: str, file: str, origin: str, origin_file: str) -> ReuseComparison:
        """Compara a foto `file` do chamado `tid` com a foto `origin_file` do chamado `origin`, de onde ela teria sido reaproveitada."""
        cur, cur_folder = ticket_facts(tid)
        org, org_folder = ticket_facts(origin)
        cur_photo, cur_path = photo_facts(tid, cur_folder, file)
        org_photo, org_path = photo_facts(origin, org_folder, origin_file)
        try:
            dist = min(distance(compute_hashes(cur_path), h) for h in hashes_with_crops(org_path, manager.cfg_base.rubric.hash_crops))
        except OSError:
            dist = None
        low = min(cur_photo.detail or 100, org_photo.detail or 100) < manager.cfg_base.rubric.hash_min_detail
        # momento de cada foto: data e hora do EXIF; sem EXIF (comum em foto reenviada por WhatsApp), o dia do envio
        def moment(ph: PhotoFacts, t: TicketFacts) -> datetime:
            return ph.taken_at or datetime.combine(ph.uploaded_on or t.supplier_submission, datetime.min.time())

        o_m, c_m = moment(org_photo, org), moment(cur_photo, cur)
        n_exif = bool(org_photo.taken_at) + bool(cur_photo.taken_at)
        basis = "exif" if n_exif == 2 else "mixed" if n_exif == 1 else "dates"
        return ReuseComparison(
            current=cur, current_photo=cur_photo, origin=org, origin_photo=org_photo, distance=dist,
            limit=manager.cfg_base.rubric.hash_max_distance_low_detail if low else manager.cfg_base.rubric.hash_max_distance,
            basis=basis, origin_moment=o_m, current_moment=c_m, chronology_ok=o_m <= c_m,
            gap_hours=round((c_m - o_m).total_seconds() / 3600, 1),
            same_branch=cur.branch_code == org.branch_code, same_supplier=cur.supplier_cnpj == org.supplier_cnpj,
        )

    @app.get("/api/tickets/{tid}/attachments/{name}")
    def attachment(tid: str, name: str) -> FileResponse:
        for base in (cfg.tickets_dir, cfg.history_dir):
            path = (base / tid / "attachments" / name).resolve()
            if path.is_relative_to(base.resolve()) and path.is_file():
                return FileResponse(path)
        raise HTTPException(404, "anexo não encontrado")

    @app.get("/api/spreadsheet-template")
    def download_template(category: str = "", symptom: str = "", scope: str = "") -> Response:
        return Response(
            spreadsheet_template(category=category, symptom=symptom, scope=scope),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="modelo_orcamento_atest.xlsx"'},
        )

    @app.post("/api/tickets", status_code=201)
    def send_ticket(
        workstream: Annotated[Workstream, Form()],
        category: Annotated[Category, Form()],
        symptom: Annotated[Symptom, Form()],
        maintenance_type: Annotated[MaintenanceType, Form()],
        moment: Annotated[Moment, Form()],
        scope: Annotated[str, Form(min_length=3)],
        branch_name: Annotated[str, Form(min_length=1)],
        branch_code: Annotated[str, Form()] = "0000",
        environment: Annotated[str, Form()] = "",
        supplier_name: Annotated[str, Form()] = "Fornecedor não informado",
        supplier_cnpj: Annotated[str, Form()] = "",
        opened_on: Annotated[date | None, Form()] = None,
        spreadsheet: Annotated[UploadFile, File()] = ...,  # type: ignore[assignment]
        attachments: Annotated[list[UploadFile], File()] = [],  # noqa: B006
    ) -> TicketSummary:
        prefix = cfg.paths.upload_id_prefix
        existing = [int(p.name) for p in cfg.tickets_dir.iterdir() if p.name.startswith(prefix) and p.name.isdigit()]
        tid = str(max(existing, default=int(prefix + "0000000")) + 1).zfill(8)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp) / "attachments"
            tmp_dir.mkdir()
            spreadsheet_name = Path(spreadsheet.filename or "quote.xlsx").name
            if not spreadsheet_name.lower().endswith((".xlsx", ".xlsm")):
                raise HTTPException(422, "O orçamento precisa ser a planilha Excel padrão (.xlsx).")
            spreadsheet_path = tmp_dir / spreadsheet_name
            spreadsheet_path.write_bytes(spreadsheet.file.read())
            try:
                quote = read_quote(spreadsheet_path)
            except QuoteError as e:
                raise HTTPException(422, f"Planilha fora do padrão: {e}. Baixe o modelo no painel.") from e
            goals = [
                {
                    "file_name": spreadsheet_name,
                    "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "size_bytes": spreadsheet_path.stat().st_size,
                    "data_upload": date.today(),
                }
            ]
            for up in attachments:
                name = Path(up.filename or "").name
                kind = ATTACHMENT_TYPES.get(Path(name).suffix.lower())
                if not name or kind is None:
                    raise HTTPException(422, f"Anexo '{name}' não suportado: envie JPG, PNG, WEBP ou PDF.")
                target = tmp_dir / name
                target.write_bytes(up.file.read())
                goals.append({"file_name": name, "content_type": kind, "size_bytes": target.stat().st_size, "data_upload": date.today()})
            try:
                data = Ticket(
                    ticket_id=tid,
                    workstream=workstream,
                    maintenance_type=maintenance_type,
                    moment=moment,
                    category=category,
                    symptom=symptom,
                    requested_scope=scope,
                    branch={"code": branch_code, "name": branch_name, "environment": environment},
                    supplier={"name": supplier_name, "cnpj": supplier_cnpj},
                    quoted_value=quote.total_value,
                    origin="upload",
                    dataset="uploaded",
                    dates={"opening": opened_on or date.today(), "supplier_submission": date.today()},
                    attachments=goals,
                )
            except ValidationError as e:
                raise HTTPException(422, f"Dados do chamado inválidos: {pt_validation_error(e.errors())}") from e
            final_target = cfg.tickets_dir / tid
            shutil.copytree(tmp_dir, final_target / "attachments")
            (final_target / "ticket.json").write_text(data.model_dump_json(indent=2), encoding="utf-8")
        event("ticket_uploaded", ticket=tid, category=category.value, attachments=len(goals))
        return summary(final_target)

    @app.delete("/api/tickets/{tid}", status_code=204)
    def delete_ticket(tid: str) -> Response:
        folder = folder_of(tid)
        if load_ticket(folder).data.origin != "upload":
            raise HTTPException(403, "Só chamados enviados pelo painel podem ser apagados.")
        shutil.rmtree(folder)
        event("ticket_deleted", ticket=tid)
        return Response(status_code=204)

    # ------------------------------------------------------------------ execuções
    @app.post("/api/runs")
    def start(request: RunRequest) -> Run:
        """Valida o pedido, cria a execução e roda em uma thread; devolve o estado inicial."""
        return manager.start(request)

    @app.get("/api/runs")
    def list_runs() -> list[dict]:
        return database.list_runs(30)

    @app.get("/api/runs/{ex_id}")
    def execution(ex_id: str, light: bool = False) -> Run:
        return manager.get(ex_id, light)

    @app.get("/api/runs/{ex_id}/validation")
    def validation_report(ex_id: str) -> dict:
        rel = database.validation(ex_id)
        if rel is None:
            raise HTTPException(404, "execução sem relatório de validação (ainda rodando ou sem gabarito)")
        return rel

    @app.get("/api/validations")
    def validations() -> list[dict]:
        return [e for e in database.list_runs(100) if e["validation"]]

    # ------------------------------------------------------------------ pareceres e feedback
    @app.get("/api/assessments/{pid}")
    def assessment(pid: int) -> Assessment:
        p = database.assessment(pid)
        if p is None:
            raise HTTPException(404, "parecer não encontrado")
        return p

    @app.get("/api/assessments/{pid}/feedback")
    def feedbacks(pid: int) -> list[Feedback]:
        return database.feedbacks(pid)

    @app.post("/api/assessments/{pid}/feedback", status_code=201)
    def register_feedback(pid: int, fb: FeedbackInput) -> Feedback:
        try:
            saved = database.save_feedback(pid, fb)
        except KeyError as e:
            raise HTTPException(404, "parecer não encontrado") from e
        event(
            "feedback",
            ticket=saved.ticket_id,
            assessment_id=pid,
            action=fb.action.value,
            final_decision=fb.final_decision.value if fb.final_decision else None,
            unfounded=fb.unfounded_findings,
        )
        return saved

    if DIST.exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="panel")
    return app
