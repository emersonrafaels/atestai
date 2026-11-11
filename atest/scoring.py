"""Etapa de score: aplica a régua da esteira, filtra pela fase, calcula notas e consolida o valor em questão."""

from __future__ import annotations

from .analysis import AnalysisContext, AnalysisStage
from .domain import Finding, Stage
from .quote import amount_at_issue
from .score import ScoreCalculator


class ScoringStage(AnalysisStage):
    """Converte os apontamentos de todas as validações em score, confiança e recomendação."""

    name = "score"
    progress = Stage.SCORE

    def run(self, ctx: AnalysisContext) -> None:
        # régua da esteira do chamado: tipos desativados (no padrão ou só nesta esteira) não contam e a severidade
        # pode ser outra; os apontamentos são criados com o padrão nas etapas e ajustados aqui
        rubric = self.cfg.rubric.for_workstream(ctx.ticket.data.workstream.value)
        scorer = ScoreCalculator(rubric)
        kinds = rubric.finding_types
        active = lambda k: kinds[k].enabled if k in kinds else True  # noqa: E731

        def adjust(fs: list[Finding]) -> list[Finding]:
            out = []
            for f in fs:
                if not active(f.kind):
                    continue
                spec = kinds.get(f.kind)
                if spec and spec.severity != f.severity:
                    f = f.model_copy(update={"severity": spec.severity, "discount": rubric.discount_by_severity[spec.severity]})
                out.append(f)
            return out

        ctx.findings = adjust(ctx.findings)
        for item in ctx.items:
            kept = adjust(item.findings)
            if [f.kind for f in kept] != [f.kind for f in item.findings]:
                item.amount_at_issue = amount_at_issue(item, kept, rubric)
            item.findings = kept
        total = sum(i.total_value for i in ctx.items) or (ctx.ticket.data.quoted_value or 0)
        ctx.amount_at_issue = round(sum(i.amount_at_issue for i in ctx.items), 2)
        ctx.amount_at_issue_pct = round(100 * ctx.amount_at_issue / total, 1) if total else 0.0
        # materialidade: muito do orçamento em questão pesa além do desconto único de cada tipo
        ctx.findings += adjust(scorer.materiality_findings(ctx.amount_at_issue_pct, total, ctx.amount_at_issue))
        ctx.findings = scorer.mark_absorbed(scorer.filter_phase(ctx.findings, self.cfg.pipeline.phase))
        ctx.score = scorer.compute(ctx.findings, ctx.confidence_reducers)
