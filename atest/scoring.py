"""Etapa de score: filtra os apontamentos pela fase da régua, calcula notas e consolida o valor em questão."""

from __future__ import annotations

from .analysis import AnalysisContext, AnalysisStage
from .domain import Stage


class ScoringStage(AnalysisStage):
    """Converte os apontamentos de todas as validações em score, confiança e recomendação."""

    name = "score"
    progress = Stage.SCORE

    def run(self, ctx: AnalysisContext) -> None:
        ctx.findings = self.scorer.filter_phase(ctx.findings, self.cfg.pipeline.phase)
        ctx.score = self.scorer.compute(ctx.findings, ctx.confidence_reducers)
        total = sum(i.total_value for i in ctx.items) or (ctx.ticket.data.quoted_value or 0)
        ctx.amount_at_issue = round(sum(i.amount_at_issue for i in ctx.items), 2)
        ctx.amount_at_issue_pct = round(100 * ctx.amount_at_issue / total, 1) if total else 0.0
