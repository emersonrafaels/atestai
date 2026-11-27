"""Categoria e solução: o chamado está na categoria e no sintoma certos? A solução resolve o problema relatado?

Roda depois das fotos e dos documentos, porque julga com TODAS as evidências, não só com o texto do escopo (a etapa de
escopo já aponta `inconsistent_scope` quando o texto contradiz a categoria). O modelo principal recebe, só em texto, o
resumo do chamado, a leitura do escopo, os itens do orçamento, a leitura das fotos e dos documentos (inclusive as
perguntas e respostas de relatório em PDF) e as categorias e sintomas do cadastro, e diz:

- a causa do problema segundo as evidências (vandalismo, desastre natural, desgaste/falha, outra, indeterminada);
- se a categoria e o sintoma servem, e quais serviriam;
- se a solução (descrição da solução + orçamento + o que foi feito) resolve o problema, em parte ou não.

A régua decide: vandalismo/desastre natural aberto com outra causa (ou o contrário) vira `cause_miscategorized`, que leva
à análise detalhada — essas causas têm tratamento próprio (B.O., seguro, verba); categoria ou sintoma errados viram
`miscategorized_ticket`; solução que não resolve, `solution_incoherent`; que resolve só parte, `solution_partially_coherent`.
"""

from __future__ import annotations

import logging

from .analysis import AnalysisContext, AnalysisStage
from .domain import Match, Stage, current_catalog
from .llm_schemas import CoherenceReview
from .observability import event
from .providers import ProviderError, TextPart
from .scope import ScopeStage

CAUSE_PT = {
    "vandalism": "vandalismo",
    "natural_disaster": "desastre natural",
    "wear_or_failure": "desgaste ou falha comum",
    "other": "outra causa",
    "undetermined": "causa indeterminada",
}
ANSWER_PT = {
    "yes": "Sim",
    "no": "Não",
    "not_applicable": "N/A",
    "blank": "em branco",
    "other": "texto",
}
MAX_ITEMS = 30  # itens do orçamento enviados ao modelo
MAX_PHOTOS = 40  # fotos descritas no pedido (a leitura de conjunto vai sempre)


class CoherenceStage(AnalysisStage):
    """Confere categoria/sintoma com a causa vista nas evidências e a coerência da solução com o problema."""

    name = "coherence"
    progress = Stage.COHERENCE

    def run(self, ctx: AnalysisContext) -> None:
        """Pede a leitura do modelo, guarda em `ctx.coherence` e gera os apontamentos da régua.

        Sem resposta válida do modelo (erro do provedor duas vezes), segue sem os apontamentos e com o redutor de
        confiança "coherence_not_checked".

        Os argumentos passados ao session.ask:
            task: "coherence" (prompt de sistema em config/prompts.toml).
            parts: um texto só (chamado, escopo, orçamento, fotos, documentos, cadastro).
            output: `CoherenceReview`.
            max_tokens: 2000; usa o modelo principal.
            meta: ticket_cause (causa especial pela categoria/sintoma do chamado), usado pelo cliente simulado.
        """
        ticket = ctx.ticket.data
        ticket_cause = self.rubric.cause_of(ticket.category.value, ticket.symptom.value)
        review = None
        for attempt in (1, 2):
            try:
                review = ctx.session.ask(
                    "coherence",
                    [TextPart(self.prompt(ctx))],
                    CoherenceReview,
                    max_tokens=2000,
                    meta={"ticket_cause": ticket_cause},
                )
                break
            except ProviderError as e:
                event(
                    "coherence_retry" if attempt == 1 else "coherence_degraded",
                    logging.WARNING,
                    error=str(e)[:300],
                )
        if review is None:
            ctx.confidence_reducers.append("coherence_not_checked")
            return
        review = self.clean(review, ticket.workstream.value, ticket.category.value)
        ctx.coherence = review
        ctx.findings += self.findings(
            review, ticket.category, ticket.symptom, ticket_cause
        )

    # ------------------------------------------------------------------ regra
    def findings(
        self, review: CoherenceReview, category, symptom, ticket_cause: str
    ) -> list:
        """Apontamentos da leitura: causa especial errada, categoria/sintoma errados e solução incoerente.

        Args:
            review: leitura do modelo (já limpa por `clean`).
            category: categoria do chamado (código com `.label`).
            symptom: sintoma do chamado (código com `.label`).
            ticket_cause: causa especial indicada pela categoria/sintoma do chamado ("" = nenhuma).

        Returns:
            Zero ou mais apontamentos: no máximo um de categoria (o de causa especial tem precedência) e um de solução.
        """
        out = []
        opened = f"{category.label} / {symptom.label}"
        seen = review.cause
        special = set(self.rubric.special_causes)
        evidence = f" ({review.cause_evidence})" if review.cause_evidence else ""
        suggestion = self.suggestion(review)
        if seen in special and seen != ticket_cause:
            # vandalismo/desastre aberto como problema comum (ou como a outra causa especial)
            out.append(
                self.scorer.finding(
                    "cause_miscategorized",
                    f"As evidências indicam {CAUSE_PT[seen]}{evidence}, mas o chamado foi aberto como {opened}"
                    + (f"; {suggestion}" if suggestion else ""),
                    opened,
                )
            )
        elif ticket_cause and seen in ("wear_or_failure", "other"):
            # aberto como vandalismo/desastre, mas as evidências mostram outra causa
            out.append(
                self.scorer.finding(
                    "cause_miscategorized",
                    f"O chamado foi aberto como {CAUSE_PT[ticket_cause]} ({opened}), mas as evidências indicam "
                    f"{CAUSE_PT[seen]}{evidence}"
                    + (f"; {suggestion}" if suggestion else ""),
                    opened,
                )
            )
        elif not review.category_fits or not review.symptom_fits:
            note = (
                review.classification_note or f"O problema não corresponde a {opened}"
            )
            out.append(
                self.scorer.finding(
                    "miscategorized_ticket",
                    note + (f"; {suggestion}" if suggestion else ""),
                    opened,
                )
            )
        if review.solution_coherent == Match.NO:
            out.append(
                self.scorer.finding(
                    "solution_incoherent",
                    review.solution_note or "A solução não trata o problema relatado",
                    "solução",
                )
            )
        elif review.solution_coherent == Match.PARTIAL:
            out.append(
                self.scorer.finding(
                    "solution_partially_coherent",
                    review.solution_note
                    or "A solução trata só parte do problema relatado",
                    "solução",
                )
            )
        return out

    @staticmethod
    def suggestion(review: CoherenceReview) -> str:
        """ "o correto seria Cftv / Vandalismo", com os nomes do cadastro (vazio sem sugestão)."""
        catalog = current_catalog()
        parts = []
        if review.suggested_category:
            parts.append(catalog.label("categories", review.suggested_category))
        if review.suggested_symptom:
            parts.append(catalog.label("symptoms", review.suggested_symptom))
        return f"o correto seria {' / '.join(parts)}" if parts else ""

    @staticmethod
    def clean(
        review: CoherenceReview, workstream: str, category: str
    ) -> CoherenceReview:
        """Descarta sugestões que não estão no cadastro (o modelo às vezes escreve o nome em vez do código) e a
        sugestão igual ao que o chamado já tem."""
        catalog = current_catalog()
        by_label = {
            kind: {e.label.casefold(): e.value for e in catalog.entries(kind)}
            for kind in ("categories", "symptoms")
        }

        def code(kind: str, value: str) -> str:
            value = value.strip()
            if value in catalog.codes(kind):
                return value
            return by_label[kind].get(value.casefold(), "")

        cat = code("categories", review.suggested_category)
        sym = code("symptoms", review.suggested_symptom)
        return review.model_copy(
            update={
                "suggested_category": "" if cat == category else cat,
                "suggested_symptom": sym,
            }
        )

    # ------------------------------------------------------------------ pedido
    def prompt(self, ctx: AnalysisContext) -> str:
        """Texto do pedido: chamado, escopo, orçamento, fotos, documentos e as opções do cadastro."""
        ticket = ctx.ticket.data
        blocks = [ticket.summary_text()]
        if ctx.scope is not None:
            blocks.append(f"LEITURA DO ESCOPO:\n{ScopeStage.describe(ctx.scope)}")
        if ctx.items:
            lines = [
                f"{i.n}. {i.description} — {i.quantity:g} {i.unit}"
                for i in ctx.items[:MAX_ITEMS]
            ]
            if len(ctx.items) > MAX_ITEMS:
                lines.append(f"(+{len(ctx.items) - MAX_ITEMS} itens)")
            blocks.append("ITENS DO ORÇAMENTO:\n" + "\n".join(lines))
        else:
            blocks.append("ITENS DO ORÇAMENTO: nenhum lido")
        blocks.append(self.photos_text(ctx))
        blocks.append(self.documents_text(ctx))
        blocks.append(self.catalog_text(ticket.workstream.value, ticket.category.value))
        return "\n\n".join(b for b in blocks if b)

    @staticmethod
    def photos_text(ctx: AnalysisContext) -> str:
        pa = ctx.photo_analysis
        if pa is None:
            return "FOTOS: não analisadas"
        names = {p.index: p.name for p in ctx.photos}
        lines = [f"Leitura de conjunto: {pa.problem_assessment}"]
        for p in pa.photos[:MAX_PHOTOS]:
            lines.append(
                f"- {names.get(p.index, f'Anexo {p.index}')}: {p.environment}; {p.what_it_shows}"
                + (
                    f" [contradiz o relatório: {p.contradicts_report}]"
                    if p.contradicts_report
                    else ""
                )
            )
        if len(pa.photos) > MAX_PHOTOS:
            lines.append(f"(+{len(pa.photos) - MAX_PHOTOS} fotos)")
        if pa.notes:
            lines.append(f"Observações: {pa.notes}")
        return "FOTOS:\n" + "\n".join(lines)

    @staticmethod
    def documents_text(ctx: AnalysisContext) -> str:
        if not ctx.documents:
            return ""
        lines = []
        for d in ctx.documents:
            head = f"- {d.file} ({d.kind})"
            if d.problem:
                head += f"; problema: {d.problem}"
            if d.solution:
                head += f"; solução: {d.solution}"
            lines.append(head)
            for a in d.answers:
                lines.append(
                    f"    • {a.question} → {ANSWER_PT.get(a.answer, a.answer)}"
                    + (f" ({a.note})" if a.note else "")
                )
            lines += [f"    divergência: {x}" for x in d.divergences]
        return "DOCUMENTOS:\n" + "\n".join(lines)

    def catalog_text(self, workstream: str, category: str) -> str:
        """Categorias da esteira e sintomas da categoria do chamado (e os genéricos), com as causas especiais."""
        catalog = current_catalog()
        cats = [
            e
            for e in catalog.categories
            if e.enabled and (not e.workstreams or workstream in e.workstreams)
        ]
        syms = [
            e
            for e in catalog.symptoms
            if e.enabled and (not e.categories or category in e.categories)
        ]
        special = [
            f"- {CAUSE_PT.get(cause, cause)}: {', '.join(codes)}"
            for cause, codes in self.rubric.special_causes.items()
        ]
        return (
            "CATEGORIAS DA ESTEIRA (código: nome):\n"
            + "\n".join(f"- {e.value}: {e.label}" for e in cats)
            + "\n\nSINTOMAS POSSÍVEIS PARA A CATEGORIA DO CHAMADO (código: nome):\n"
            + "\n".join(f"- {e.value}: {e.label}" for e in syms)
            + (
                "\n\nCÓDIGOS QUE INDICAM CAUSA ESPECIAL (categoria ou sintoma):\n"
                + "\n".join(special)
                if special
                else ""
            )
        )
