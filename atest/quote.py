"""Validação 2 — Orçamento: o que foi cobrado faz sentido para o que foi pedido?

1. A planilha Excel é lida por regra (repository.read_ticket_quote), sem LLM; o que ela não trouxer vem do chamado.
2. O modelo principal confere cada item contra o escopo: aderente / fora do escopo / a justificar, quantidade
   plausível, duplicidade e código equivalente na LPU.
3. Regras determinísticas: preço × LPU, duplicidade textual, coerência planilha × chamado e valor em questão
   (item inteiro ou só o excedente, conforme config/rubric.toml).
"""

from __future__ import annotations

import difflib
import logging

from .analysis import AnalysisContext, AnalysisStage
from .domain import AmountAtIssue, EvaluatedItem, Finding, ItemClassification, LpuItem, Match, Quote, QuoteItem, Rubric, Stage
from .formatting import brl, normalize_text, normalize_unit, same_unit
from .llm import LlmSession
from .llm_schemas import ItemReview, QuoteReview, ScopeReading
from .observability import event
from .providers import TextPart
from .repository import LoadedTicket, QuoteError, read_ticket_quote
from .scope import ScopeStage

DUPLICATE_SIMILARITY = 0.8  # descrição ≥ 80% parecida conta como duplicidade (com mesma unidade, quantidade e preço)


class QuoteStage(AnalysisStage):
    """Confere o orçamento contra o escopo e contra a LPU, item a item."""

    name = "quote"
    progress = Stage.QUOTE

    def run(self, ctx: AnalysisContext) -> None:
        try:
            quote = read_ticket_quote(ctx.ticket)
        except (QuoteError, IndexError) as e:
            ctx.confidence_reducers.append("unreadable_quote")
            ctx.quote_notes.append(f"Orçamento não lido: {e}")
            return
        assert ctx.scope is not None
        review = self.review_items(ctx.session, ctx.ticket, ctx.scope, quote)
        items, findings, notes = self.flag(ctx.ticket, quote, review)
        ctx.items, ctx.quote_notes = items, notes + self.unchecked_services(ctx.scope, review)
        ctx.service_coverage = sorted(review.service_coverage, key=lambda c: c.n)
        ctx.findings += findings

    @staticmethod
    def requested_services(scope: ScopeReading) -> list[str]:
        """Serviços pedidos (escopo e descrição da solução), numerados no pedido ao modelo."""
        return [s.strip() for s in scope.requested_services if s.strip()]

    def unchecked_services(self, scope: ScopeReading, review: QuoteReview) -> list[str]:
        """Serviço pedido que o modelo não conferiu contra o orçamento: fica como observação (nada passa calado)."""
        done = {c.n for c in review.service_coverage}
        missing = [s for n, s in enumerate(self.requested_services(scope), 1) if n not in done]
        if missing:
            event("quote_coverage_incomplete", logging.WARNING, missing=missing)
            return ["Serviço pedido não conferido contra o orçamento: " + "; ".join(missing)]
        return []

    # ------------------------------------------------------------------ conferência pelo modelo
    def review_items(self, session: LlmSession, ticket: LoadedTicket, scope: ScopeReading, quote: Quote) -> QuoteReview:
        """Pede ao modelo principal a classificação de cada item, com a LPU da esteira no prompt de sistema."""
        items = "\n".join(
            f"{i.n}. {i.description} | {i.quantity:g} {i.unit} | unit. R$ {i.unit_value:.2f} | total R$ {i.total_value:.2f}"
            + ("" if i.lpu else " | FORA DA LPU")
            for i in quote.items
        )
        services = "\n".join(f"{n}. {s}" for n, s in enumerate(self.requested_services(scope), 1)) or "1. " + ticket.data.requested_scope
        workstream = ticket.data.workstream.value
        system = f"{session.system('quote_review')}\n\nTABELA DE REFERÊNCIA (LPU) DA ESTEIRA {workstream}:\n{self.references.lpu_text(workstream)}"
        text = (
            f"{ticket.data.summary_text()}\n\nLEITURA DO ESCOPO:\n{ScopeStage.describe(scope)}"
            f"\n\nITENS DO ORÇAMENTO:\n{items}"
            f"\n\nSERVIÇOS PEDIDOS (um registro em service_coverage para cada número):\n{services}"
            "\n\nClassifique todos os itens e confira a cobertura de todos os serviços pedidos."
        )
        # a resposta cresce com os itens (classificação e motivo de cada um) e com os serviços pedidos (cobertura):
        # limite fixo cortava orçamentos maiores
        n_services = max(1, services.count("\n") + 1)
        max_tokens = min(12000, 2500 + 450 * len(quote.items) + 300 * n_services)
        return session.ask("quote_review", [TextPart(text)], QuoteReview, system=system, max_tokens=max_tokens)

    # ------------------------------------------------------------------ regras
    def spreadsheet_mismatches(self, ticket: LoadedTicket, quote: Quote) -> list[str]:
        """Diferenças entre o que o fornecedor pôs na planilha e o que está no chamado."""
        t = ticket.data
        diffs = []
        if quote.ticket_id != t.ticket_id:
            diffs.append(f"planilha indica o chamado {quote.ticket_id}, não {t.ticket_id}")
        if quote.category != t.category:
            diffs.append(f"categoria na planilha é {quote.category.label}, no chamado é {t.category.label}")
        if quote.symptom != t.symptom:
            diffs.append(f"sintoma na planilha é {quote.symptom.label}, no chamado é {t.symptom.label}")
        if normalize_text(quote.scope) != normalize_text(t.requested_scope):
            diffs.append("escopo da planilha diferente do escopo do chamado")
        if t.quoted_value is not None and abs(quote.total_value - t.quoted_value) > self.rubric.spreadsheet_value_tolerance:
            diffs.append(f"soma dos itens {brl(quote.total_value)} × valor orçado no chamado {brl(t.quoted_value)}")
        return diffs

    def flag(self, ticket: LoadedTicket, quote: Quote, review: QuoteReview) -> tuple[list[EvaluatedItem], list[Finding], list[str]]:
        """Itens avaliados, apontamentos e observações (não pontuadas)."""
        lpu = self.references.lpu.get(ticket.data.workstream.value, {})
        by_n: dict[int, ItemReview] = {r.n: r for r in review.items}
        items: list[EvaluatedItem] = []
        notes: list[str] = []
        general: list[Finding] = []

        if diffs := self.spreadsheet_mismatches(ticket, quote):
            general.append(self.scorer.finding("spreadsheet_mismatch", "; ".join(diffs).capitalize(), quote.file))
        uncovered = [c.service.strip() for c in review.service_coverage if c.covered == Match.NO and c.service.strip()]
        if uncovered and "scope_not_quoted" in self.rubric.finding_types:
            evidence = "Pedido no chamado sem item no orçamento: " + "; ".join(uncovered)
            general.append(self.scorer.finding("scope_not_quoted", evidence, "escopo × orçamento"))
        for c in review.service_coverage:  # item que resolve só parte do pedido: o engenheiro registra o que falta
            if c.covered == Match.PARTIAL and c.service.strip():
                notes.append(f"Coberto só em parte: {c.service.strip()}" + (f" ({c.note.strip()})" if c.note.strip() else ""))

        for item in quote.items:
            r = by_n.get(item.n)
            label = f"item {item.n}: {item.description}"
            findings = self._classification_findings(item, r, label)
            findings += self._quantity_findings(item, r, label)
            ref = lpu.get(r.lpu_code) if r and item.lpu else None  # item fora da LPU não tem preço de referência na tabela
            price_finding, note = self._price_check(item, ref, label)
            findings += price_finding
            notes += note
            if dup := (r.duplicate_of if r else 0) or self._textual_duplicate(item, items):
                findings.append(self.scorer.finding("duplicate_item", f"Mesmo item já cobrado na linha {dup}", label, item.total_value))
            qmax = r.expected_quantity_max if r and r.expected_quantity_max > 0 else None
            items.append(
                EvaluatedItem(
                    **item.model_dump(),
                    classification=r.classification if r else ItemClassification.COMPLIANT,
                    reason=r.reason if r else "",
                    lpu_code=(r.lpu_code if r else "NO_REFERENCE") if item.lpu else "NO_REFERENCE",
                    reference_price=ref.reference_price if ref else None,
                    expected_quantity_max=qmax,
                    amount_at_issue=self._amount_at_issue(item, findings),
                    findings=findings,
                )
            )
        if review.notes:
            notes.append(review.notes)
        return items, general + [f for i in items for f in i.findings], notes

    def _classification_findings(self, item: QuoteItem, r: ItemReview | None, label: str) -> list[Finding]:
        if r and r.classification == ItemClassification.OUT_OF_SCOPE:
            return [self.scorer.finding("out_of_scope_item", r.reason, label, item.total_value)]
        if r and r.classification == ItemClassification.TO_JUSTIFY:
            return [self.scorer.finding("unjustified_replacement", r.reason, label, item.total_value)]
        return []

    def _quantity_findings(self, item: QuoteItem, r: ItemReview | None, label: str) -> list[Finding]:
        qmax = r.expected_quantity_max if r and r.expected_quantity_max > 0 else None
        if not r or (r.plausible_quantity and not (qmax and item.quantity > qmax + 1e-9)):
            return []
        if qmax and item.quantity > qmax:
            excess = round((item.quantity - qmax) * item.unit_value, 2)
            evidence = f"Cobrado {item.quantity:g} {item.unit}; esperado até {qmax:g} {item.unit} para o escopo (excedente {brl(excess)})"
            return [self.scorer.finding("quantity_above_expected", evidence, label, excess)]
        if not qmax:
            # o modelo não consegue estimar a quantidade pelo escopo: não é "acima", é "não dá para conferir"
            evidence = f"Cobrado {item.quantity:g} {item.unit}; o escopo não informa a quantidade, então não dá para conferir"
            return [self.scorer.finding("unverifiable_quantity", evidence, label, item.total_value)]
        evidence = f"Cobrado {item.quantity:g} {item.unit}, acima do plausível para o escopo"
        return [self.scorer.finding("quantity_above_expected", evidence, label, item.total_value)]

    def _price_check(self, item: QuoteItem, ref: LpuItem | None, label: str) -> tuple[list[Finding], list[str]]:
        if ref is None:
            return [], []
        if not same_unit(item.unit, ref.unit, item.quantity):
            msg = f"Item {item.n}: cobrado em '{item.unit}' e a referência {ref.code} da LPU é em '{ref.unit}'; o preço não foi comparado"
            return [], [msg]
        if item.unit_value <= ref.reference_price * (1 + self.rubric.price_tolerance_pct / 100):
            return [], []
        p, rp = item.unit_value, ref.reference_price
        excess = round((p - rp) * item.quantity, 2)
        evidence = f"{brl(p)} por {item.unit} contra referência {ref.code} de {brl(rp)} (+{(p / rp - 1) * 100:.0f}%; excedente {brl(excess)})"
        return [self.scorer.finding("price_above_reference", evidence, label, excess)], []

    @staticmethod
    def _textual_duplicate(item: QuoteItem, previous: list[EvaluatedItem]) -> int:
        """Número da linha anterior com mesma unidade, quantidade e preço e descrição parecida; 0 se não houver."""
        for prev in previous:
            same_terms = (
                normalize_unit(prev.unit) == normalize_unit(item.unit)
                and prev.quantity == item.quantity
                and abs(prev.unit_value - item.unit_value) < 0.01
            )
            if same_terms:
                similarity = difflib.SequenceMatcher(None, normalize_text(prev.description), normalize_text(item.description)).ratio()
                if similarity >= DUPLICATE_SIMILARITY:
                    return prev.n
        return 0

    def _amount_at_issue(self, item: QuoteItem, findings: list[Finding]) -> float:
        return amount_at_issue(item, findings, self.rubric)


def amount_at_issue(item: QuoteItem, findings: list[Finding], rubric: Rubric) -> float:
    """Item inteiro se algum apontamento questiona o item; senão a soma dos excedentes (limitada ao total do item)."""
    if not findings:
        return 0.0
    kinds = rubric.finding_types
    if any(kinds[f.kind].amount_at_issue == AmountAtIssue.ITEM for f in findings):
        return item.total_value
    excess = sum(f.amount_at_issue for f in findings if kinds[f.kind].amount_at_issue == AmountAtIssue.EXCESS)
    return round(min(item.total_value, excess), 2)
