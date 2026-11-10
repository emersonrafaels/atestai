"""Execução em lote (o "batch a cada hora" do MVP): síncrona ou pela Message Batches API, com persistência."""

from __future__ import annotations

import csv
import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .attachments import HashCache
from .config import ROOT, BatchMode, Mode, Settings
from .costs import CostCalculator
from .database import Database
from .domain import Assessment, Recommendation, Stage
from .evaluation import Evaluation, GroundTruthEvaluator
from .formatting import error_message
from .llm import BatchClient, LlmClient, ProviderClient
from .observability import context, event
from .photos import PhotoIndex
from .pipeline import Orchestrator
from .repository import References, list_tickets, load_ticket
from .simulated import SimulatedClient
from .validation import ValidationReport, ValidationReporter

log = logging.getLogger(__name__)
OnProgress = Callable[[str, Stage], None]
OnComplete = Callable[[str, Assessment | None, str | None], None]


class BatchResult(BaseModel):
    """Resultado de uma execução: pareceres, erros, lotes enviados, avaliação contra o gabarito e saídas."""

    run_id: str
    assessments: list[Assessment] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)
    api_batches: list[str] = Field(default_factory=list)
    evaluation: Evaluation | None = None
    validation: ValidationReport | None = None
    output_folder: Path | None = None

    @property
    def tokens(self) -> tuple[int, int]:
        """(tokens de entrada, tokens de saída) somados de todas as chamadas."""
        calls = [c for p in self.assessments for c in p.llm_calls]
        return sum(c.input_tokens for c in calls), sum(c.output_tokens for c in calls)

    @property
    def cost_usd(self) -> float:
        return round(sum(p.cost_usd for p in self.assessments), 6)


def new_run_id() -> str:
    """Id da execução: data e hora + sufixo aleatório curto."""
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


class ComponentFactory:
    """Monta cliente de LLM, índice de fotos e orquestrador a partir da configuração."""

    _hash_caches: dict[Path, HashCache] = {}  # um cache por arquivo, compartilhado pelas execuções do processo (painel)

    def __init__(self, cfg: Settings):
        self.cfg = cfg

    def client(self) -> LlmClient:
        """Simulado, síncrono por provedor ou Message Batches, conforme [execution.mode] e [batch.kind]."""
        if self.cfg.execution.mode == Mode.SIMULATED:
            return SimulatedClient(self.cfg, delay_s=self.cfg.panel.simulated_delay_s, noise=self.cfg.validation.simulated_noise)
        if self.cfg.batch.kind == BatchMode.BATCH:
            return BatchClient(self.cfg)
        return ProviderClient(self.cfg)

    def hash_cache(self) -> HashCache:
        """Cache de hashes de fotos compartilhado pelo processo."""
        file = self.cfg.cache_dir / "photo_hashes.json"
        if file not in self._hash_caches:
            self._hash_caches[file] = HashCache(file)
        return self._hash_caches[file]

    def photo_index(self) -> PhotoIndex | None:
        """Índice de fotos do histórico e dos chamados atuais (só na Fase 2 da régua)."""
        if self.cfg.pipeline.phase < 2:
            return None
        return PhotoIndex.from_folders(self.cfg.history_dir, self.cfg.tickets_dir, crops=self.cfg.rubric.hash_crops, cache=self.hash_cache())

    def orchestrator(self, client: LlmClient | None = None) -> Orchestrator:
        """Orquestrador com as referências, o cliente e o índice de fotos da configuração."""
        return Orchestrator(self.cfg, References(self.cfg), client or self.client(), self.photo_index())


class RunOutputWriter:
    """Grava as saídas de uma execução em output/runs/<id>/: pareceres, JSON lines, CSVs e relatórios."""

    SUMMARY_COLUMNS = [
        "ticket_id", "workstream", "category", "symptom", "supplier", "quoted_value", "recommendation", "score",
        "scope_grade", "quote_grade", "photo_grade", "confidence", "finding_types", "amount_at_issue", "cost_brl", "summary",
    ]  # fmt: skip

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)

    def write(self, result: BatchResult) -> Path:
        """Grava todas as saídas e devolve a pasta da execução."""
        folder = self.output_dir / "runs" / result.run_id
        (folder / "assessments").mkdir(parents=True, exist_ok=True)
        self._assessments(folder, result.assessments)
        self._summary(folder / "summary.csv", result.assessments)
        self._checklist_returns(folder / "checklist_returns.csv", result.assessments)
        if result.validation:
            (folder / "validation.json").write_text(result.validation.model_dump_json(indent=2), encoding="utf-8")
        if result.evaluation:
            (folder / "evaluation.json").write_text(result.evaluation.model_dump_json(indent=2), encoding="utf-8")
        result.output_folder = folder
        return folder

    @staticmethod
    def _assessments(folder: Path, assessments: list[Assessment]) -> None:
        with open(folder / "assessments.jsonl", "w", encoding="utf-8") as jl:
            for p in assessments:
                (folder / "assessments" / f"{p.ticket_id}.json").write_text(p.model_dump_json(indent=2), encoding="utf-8")
                jl.write(p.model_dump_json() + "\n")

    def _summary(self, path: Path, assessments: list[Assessment]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(self.SUMMARY_COLUMNS)
            for p in assessments:
                g = p.grades
                w.writerow(
                    [
                        p.ticket_id, p.workstream.value, p.category.value, p.symptom.value, p.supplier, p.quoted_value,
                        p.recommendation.value, p.score, g and g.scope, g and g.quote, g and g.photos,
                        p.confidence and p.confidence.value, ",".join(sorted({x.kind for x in p.findings})),
                        p.amount_at_issue, p.cost_brl, p.summary,
                    ]
                )  # fmt: skip

    @staticmethod
    def _checklist_returns(path: Path, assessments: list[Assessment]) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["ticket_id", "supplier", "missing", "supplier_message"])
            for p in assessments:
                if p.recommendation == Recommendation.CHECKLIST_RETURNED and p.checklist:
                    w.writerow([p.ticket_id, p.supplier, ",".join(p.checklist.missing), p.supplier_message])


class BatchRunner:
    """Roda um conjunto de chamados, grava as saídas e, se houver banco, persiste execução, pareceres e chamadas."""

    def __init__(self, cfg: Settings, orchestrator: Orchestrator | None = None, database: Database | None = None):
        self.cfg = cfg
        self.orchestrator = orchestrator or ComponentFactory(cfg).orchestrator()
        self.database = database
        self.costs = CostCalculator(cfg)

    @property
    def client(self) -> LlmClient:
        return self.orchestrator.client

    def run(
        self,
        ids: list[str] | None = None,
        *,
        run_id: str | None = None,
        on_progress: OnProgress | None = None,
        on_complete: OnComplete | None = None,
        label: str = "",
    ) -> BatchResult:
        """Roda os chamados (todos ou os ids pedidos) e devolve o resultado da execução."""
        folders = list_tickets(self.cfg.tickets_dir, ids)
        result = BatchResult(run_id=run_id or new_run_id())
        mode = "simulated" if self.client.simulated else "api"
        batch_mode = "batch" if self.client.via_batch else "sync"
        if self.database:
            self.database.create_run(
                result.run_id,
                mode=mode,
                batch_mode=batch_mode,
                phase=self.cfg.pipeline.phase,
                environment=self.cfg.environment,
                models={"main": self.cfg.models.main, "fast": self.cfg.models.fast},
                tickets=[p.name for p in folders],
                label=label,
                signature=self.cfg.signature(),
            )
        with context(run=result.run_id):
            event("run_start", tickets=len(folders), mode=mode, batch_mode=batch_mode, phase=self.cfg.pipeline.phase)
            self._analyze_all(folders, result, on_progress, on_complete)
            self._evaluate(result)
            RunOutputWriter(self.cfg.output_dir).write(result)
            self._complete(result)
        return result

    def _analyze_all(self, folders: list[Path], result: BatchResult, on_progress: OnProgress | None, on_complete: OnComplete | None) -> None:
        # no modo batch, todos os pipelines rodam juntos para que cada rodada de chamadas vire um único lote
        client = self.client
        via_batch_api = isinstance(client, BatchClient)
        workers = max(1, len(folders)) if via_batch_api else self.cfg.pipeline.parallel

        def analyze(folder: Path) -> Assessment:
            if via_batch_api:
                client.register_pipeline()
            try:
                return self.orchestrator.analyze(load_ticket(folder), on_progress, result.run_id)
            finally:
                if via_batch_api:
                    client.close_pipeline()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(analyze, p): p.name for p in folders}
            for future in as_completed(futures):
                ticket_id = futures[future]
                try:
                    assessment = future.result()
                except Exception as e:  # um chamado com erro não derruba o lote
                    log.exception("erro no chamado %s", ticket_id, extra={"ticket_error": ticket_id})
                    result.errors[ticket_id] = error_message(e)
                    if on_complete:
                        on_complete(ticket_id, None, result.errors[ticket_id])
                    continue
                if self.database:
                    self.database.save_assessment(assessment)
                result.assessments.append(assessment)
                if on_complete:
                    on_complete(ticket_id, assessment, None)
        if via_batch_api:
            result.api_batches = list(client.batches)
            client.close()
        result.assessments.sort(key=lambda p: p.ticket_id)

    def _evaluate(self, result: BatchResult) -> None:
        """Compara com o gabarito (quando há) e gera o relatório de validação."""
        if not self.cfg.execution.evaluate_against_ground_truth:
            return
        evaluation = GroundTruthEvaluator(self.cfg.ground_truth_dir).evaluate(result.assessments)
        if not evaluation.n:
            return
        result.evaluation = evaluation
        result.validation = ValidationReporter(self.cfg).build(result.assessments)
        if self.database:
            self.database.save_validation(result.run_id, result.validation.model_dump(mode="json"))

    def _complete(self, result: BatchResult) -> None:
        tokens_in, tokens_out = result.tokens
        if self.database:
            self.database.complete_run(
                result.run_id,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                cost_usd=result.cost_usd,
                cost_brl=self.costs.to_brl(result.cost_usd),
                evaluation=result.evaluation.model_dump(mode="json") if result.evaluation else None,
                errors=result.errors,
                output_folder=self._relative(result.output_folder),
                batches=result.api_batches,
            )
        event(
            "run_end",
            assessments=len(result.assessments),
            errors=len(result.errors),
            cost_usd=result.cost_usd,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            api_batches=result.api_batches,
        )

    @staticmethod
    def _relative(p: Path | None) -> str | None:
        if p is None:
            return None
        return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
