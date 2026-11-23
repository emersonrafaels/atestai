"""Etapa de score: aplica a régua da esteira, filtra pela fase, calcula notas e consolida o valor em questão."""

from __future__ import annotations

from .analysis import AnalysisContext, AnalysisStage
from .domain import Finding, Match, Moment, Stage
from .photos import EXECUTION_ONLY, countable_items
from .quote import amount_at_issue
from .score import Measures, ScoreCalculator


class ScoringStage(AnalysisStage):
    """Converte os apontamentos de todas as validações em score, confiança e recomendação."""

    name = "score"
    progress = Stage.SCORE

    def run(self, ctx: AnalysisContext) -> None:
        """Ajusta os apontamentos à régua da esteira, calcula o valor em questão e preenche `ctx.score`.

        Passos: (1) descarta tipos desativados e, na aprovação do orçamento, os que cobram o serviço feito, e
        aplica severidade/devolução da esteira; (2) recalcula o valor em questão de cada item e o total (`total` =
        soma dos itens ou, sem itens, o valor orçado no chamado); (3) filtra pela fase e aplica o desconto
        proporcional; (4) soma o apontamento de materialidade; (5) marca absorvidos e calcula notas e recomendação.
        """
        # régua da esteira do chamado: tipos desativados (no padrão ou só nesta esteira) não contam e a severidade
        # pode ser outra; os apontamentos são criados com o padrão nas etapas e ajustados aqui
        rubric = self.cfg.rubric.for_workstream(ctx.ticket.data.workstream.value)
        scorer = ScoreCalculator(rubric)
        kinds = rubric.finding_types
        active = lambda k: kinds[k].enabled if k in kinds else True  # noqa: E731

        quote_stage = ctx.ticket.data.moment == Moment.QUOTE

        def adjust(fs: list[Finding]) -> list[Finding]:
            out = []
            for f in fs:
                if not active(f.kind) or (
                    quote_stage and f.kind in EXECUTION_ONLY
                ):  # aprovação do orçamento: sem cobrar o depois
                    continue
                spec = kinds.get(f.kind)
                if spec and (
                    spec.severity != f.severity
                    or spec.returns != f.returns
                    or spec.review != f.review
                    or spec.caveats != f.caveats
                ):
                    update = {
                        "severity": spec.severity,
                        "discount": rubric.discount_by_severity[spec.severity],
                        "returns": spec.returns,
                        "review": spec.review,
                        "caveats": spec.caveats,
                    }
                    f = f.model_copy(update=update)
                out.append(f)
            return out

        # (1) Ajusta os apontamentos gerais e os de cada item à régua da esteira.
        ctx.findings = adjust(ctx.findings)
        for item in ctx.items:
            kept = adjust(item.findings)
            # Algum apontamento do item caiu: o valor em questão do item precisa ser refeito.
            if [f.kind for f in kept] != [f.kind for f in item.findings]:
                item.amount_at_issue = amount_at_issue(item, kept, rubric)
            item.findings = kept
        # (2) Total do orçamento (soma dos itens ou, sem planilha lida, o valor orçado no chamado) e valor em questão.
        total = sum(i.total_value for i in ctx.items) or (
            ctx.ticket.data.quoted_value or 0
        )
        ctx.amount_at_issue = round(sum(i.amount_at_issue for i in ctx.items), 2)
        ctx.amount_at_issue_pct = (
            round(100 * ctx.amount_at_issue / total, 1) if total else 0.0
        )
        # (3) Filtra pela fase e aplica o desconto proporcional ao que foi enviado (fração atingida de cada tipo).
        findings = scorer.proportional(
            scorer.filter_phase(ctx.findings, self.cfg.pipeline.phase),
            self.measures(ctx, total),
        )
        # (4) Materialidade: o valor em questão limita a nota de Orçamento (além do desconto único de cada tipo).
        findings += adjust(
            scorer.materiality_findings(
                findings, ctx.amount_at_issue_pct, total, ctx.amount_at_issue
            )
        )
        # (5) Marca os absorvidos (aparecem no parecer, mas não descontam) e calcula notas, score e recomendação.
        ctx.findings = scorer.mark_absorbed(
            scorer.filter_phase(findings, self.cfg.pipeline.phase)
        )
        ctx.score = scorer.compute(
            ctx.findings, ctx.confidence_reducers, ctx.amount_at_issue_pct
        )

    @staticmethod
    def measures(ctx: AnalysisContext, total: float) -> Measures:
        """O que o fornecedor enviou: base de cada fração (fotos, itens, documentos, serviços pedidos, valor).

        Args:
            ctx: contexto do chamado depois das etapas de conferência.
            total: valor total do orçamento em R$.

        Returns:
            As medidas usadas por `ScoreCalculator.proportional`.
        """
        coverage = [c.covered for c in ctx.service_coverage]
        # Fotos lidas pelo modelo; se ele não leu nenhuma, usa as enviadas.
        photos = len(ctx.photo_analysis.photos) if ctx.photo_analysis else 0
        return Measures(
            total_value=total,
            photos=photos or len(ctx.photos),
            items=len(countable_items(ctx.items)) or len(ctx.items),
            documents=len(ctx.documents),
            services=len(coverage),
            services_missing=sum(c == Match.NO for c in coverage),
            services_partial=sum(c == Match.PARTIAL for c in coverage),
        )
