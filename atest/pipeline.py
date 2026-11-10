"""Orquestrador do Atest.AI: checklist → escopo → orçamento × escopo → fotos → score → parecer.

O orquestrador não conhece regra de negócio: ele roda as etapas (`AnalysisStage`) em ordem sobre um
`AnalysisContext`, mede o tempo de cada uma, avisa o progresso e monta o `Assessment` final. Trocar, remover ou
acrescentar uma etapa é passar outra lista em `stages`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from .analysis import AnalysisContext, AnalysisStage
from .assessment import AssessmentStage
from .checklist import ChecklistStage
from .config import Settings
from .costs import CostCalculator
from .domain import Assessment, Stage
from .llm import LlmClient, LlmSession
from .observability import context, event, timed_stage
from .photos import PhotoIndex, PhotoStage
from .quote import QuoteStage
from .repository import LoadedTicket, References
from .scope import ScopeStage
from .score import ScoreCalculator
from .scoring import ScoringStage

OnProgress = Callable[[str, Stage], None]


class Orchestrator:
    """Analisa um chamado de ponta a ponta e devolve o parecer."""

    def __init__(
        self,
        cfg: Settings,
        references: References,
        client: LlmClient,
        photo_index: PhotoIndex | None = None,
        stages: Sequence[AnalysisStage] | None = None,
    ):
        self.cfg = cfg
        self.references = references
        self.client = client
        self.scorer = ScoreCalculator(references.rubric)
        self.costs = CostCalculator(cfg)
        index = photo_index if cfg.pipeline.phase >= 2 else None
        self.stages = list(stages) if stages is not None else self.default_stages(index)

    def default_stages(self, photo_index: PhotoIndex | None) -> list[AnalysisStage]:
        """As seis etapas do deck, na ordem."""
        args = (self.cfg, self.references, self.scorer)
        return [
            ChecklistStage(*args),
            ScopeStage(*args),
            QuoteStage(*args),
            PhotoStage(*args, index=photo_index),
            ScoringStage(*args),
            AssessmentStage(*args),
        ]

    def analyze(self, ticket: LoadedTicket, on_progress: OnProgress | None = None, run_id: str | None = None) -> Assessment:
        """Roda todas as etapas sobre o chamado (ou até uma etapa encerrar a análise)."""
        with context(run=run_id, ticket=ticket.id):
            started = time.perf_counter()
            ctx = AnalysisContext(ticket=ticket, session=LlmSession(self.client, self.cfg, ticket.id), run_id=run_id)
            event("ticket_start", category=ticket.data.category.value, workstream=ticket.data.workstream.value, mode=self._mode)
            for stage in self.stages:
                if on_progress:
                    on_progress(ticket.id, stage.progress)
                with timed_stage(stage.name, ctx.durations):
                    stage.run(ctx)
                if ctx.halted:
                    break
            assessment = self._build(ctx, started)
            if on_progress:
                on_progress(ticket.id, Stage.DONE)
            event(
                "ticket_end",
                recommendation=assessment.recommendation.value,
                score=assessment.score,
                cost_usd=assessment.cost_usd,
                duration_s=assessment.duration_s,
                findings=sorted({f.kind for f in assessment.findings}),
            )
            return assessment

    @property
    def _mode(self) -> str:
        return "simulated" if self.client.simulated else "api"

    def _header(self, ticket: LoadedTicket, run_id: str | None) -> dict[str, Any]:
        """Campos do parecer que vêm do chamado e da configuração (rastreabilidade)."""
        t = ticket.data
        return {
            "ticket_id": ticket.id,
            "workstream": t.workstream,
            "category": t.category,
            "symptom": t.symptom,
            "maintenance_type": t.maintenance_type,
            "moment": t.moment,
            "branch": t.branch,
            "supplier": t.supplier.name,
            "quoted_value": t.quoted_value,
            "requested_scope": t.requested_scope,
            "generated_at": datetime.now(),
            "rubric_version": self.references.rubric.version,
            "prompts_version": self.cfg.prompts.version,
            "config_signature": self.cfg.signature(),
            "phase": self.cfg.pipeline.phase,
            "run_id": run_id,
            "mode": self._mode,
            "batch_mode": "batch" if self.client.via_batch else "sync",
            "models": {"main": self.cfg.models.main, "fast": self.cfg.models.fast},
        }

    def _results(self, ctx: AnalysisContext) -> dict[str, Any]:
        """Campos produzidos pelas etapas (ou pela etapa que encerrou a análise)."""
        if ctx.halted:
            return {"checklist": ctx.checklist, "attachments": ctx.attachments, **(ctx.halt or {})}
        assert ctx.score is not None and ctx.photo_analysis is not None and ctx.text is not None and ctx.scope is not None
        return {
            "checklist": ctx.checklist,
            "attachments": ctx.attachments,
            **ctx.score.model_dump(),
            "findings": ctx.findings,
            "amount_at_issue": ctx.amount_at_issue,
            "amount_at_issue_pct": ctx.amount_at_issue_pct,
            "scope": ctx.scope.model_dump(mode="json"),
            "items": ctx.items,
            "quote_notes": ctx.quote_notes,
            "photos": PhotoStage.evaluated_photos(ctx.photo_analysis, ctx.photos, ctx.integrity),
            "photo_summary": ctx.photo_analysis.model_dump(
                mode="json", include={"has_before_photo", "done_service", "done_justification", "items_without_photo", "notes"}
            ),
            "summary": ctx.text.summary,
            "supplier_message": ctx.text.supplier_message,
        }

    def _build(self, ctx: AnalysisContext, started: float) -> Assessment:
        usd = round(sum(c.cost_usd for c in ctx.session.calls), 6)
        return Assessment(
            **self._header(ctx.ticket, ctx.run_id),
            **self._results(ctx),
            llm_calls=ctx.session.calls,
            duration_s=round(time.perf_counter() - started, 2),
            stage_durations_s=ctx.durations,
            cost_usd=usd,
            cost_brl=self.costs.to_brl(usd),
        )
