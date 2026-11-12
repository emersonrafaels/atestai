"""Leitura de documentos (OCR) — o que os documentos anexados dizem confere com o chamado?

Documentos chegam como foto (relatório de atendimento preenchido à mão, termo de conclusão fotografado, print de
anúncio com preço) ou PDF. O modelo principal (visão) transcreve cada um e extrai os campos que interessam à
conferência: data e horário do atendimento, agência, problema, solução, assinatura e preços citados. As regras
abaixo transformam a leitura em apontamentos, como na análise das fotos:

- documento ilegível                         → unreadable_document (reduz a confiança);
- documento de outro chamado/serviço         → document_mismatch;
- data do atendimento fora da janela do chamado → document_date_inconsistent;
- preço de mercado anexado abaixo do cobrado → price_above_market (no orçamento, sobre o excedente).
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from .analysis import AnalysisContext, AnalysisStage
from .attachments import attachment_parts
from .domain import Attachment, AttachmentCategory, ClassifiedAttachment, EvaluatedDocument, EvaluatedItem, Finding, Match, Moment, Stage
from .formatting import asks_for_after_service, brl
from .llm import LlmSession
from .llm_schemas import DocumentAnalysis, ScopeReading
from .observability import event
from .providers import Part, ProviderError, TextPart
from .quote import amount_at_issue
from .repository import LoadedTicket
from .scope import ScopeStage

DOC_TYPES = {"application/pdf"}
NOT_DOCUMENTS = {AttachmentCategory.QUOTE_DOC}  # a planilha é lida por regra (repository.read_quote)


def parse_date(text: str) -> date | None:
    """Data escrita no documento (dd/mm/aaaa, dd/mm/aa ou aaaa-mm-dd); None se não der para ler."""
    text = (text or "").strip()
    for pattern, fmt in ((r"\d{1,2}/\d{1,2}/\d{4}", "%d/%m/%Y"), (r"\d{1,2}/\d{1,2}/\d{2}\b", "%d/%m/%y"), (r"\d{4}-\d{2}-\d{2}", "%Y-%m-%d")):
        if m := re.search(pattern, text):
            try:
                return datetime.strptime(m.group(0), fmt).date()
            except ValueError:
                return None
    return None


class DocumentStage(AnalysisStage):
    """Transcreve os documentos anexados (imagem ou PDF) e confere o que dizem contra o chamado e o orçamento."""

    name = "documents"
    progress = Stage.DOCUMENTS

    def run(self, ctx: AnalysisContext) -> None:
        docs = self.ticket_documents(ctx.ticket, ctx.attachments)
        if not docs:
            ctx.documents = []
            return
        assert ctx.scope is not None
        analysis = None
        for attempt in (1, 2):  # falha de formato da resposta costuma ser pontual: tenta de novo antes de desistir
            try:
                analysis = self.analyze(ctx.session, ctx.ticket, ctx.scope, ctx.items, docs)
                break
            except ProviderError as e:
                event("documents_retry" if attempt == 1 else "documents_degraded", logging.WARNING, error=str(e)[:300], documents=len(docs))
        if analysis is None:  # segue sem a leitura dos documentos, com redutor de confiança
            ctx.documents = []
            ctx.confidence_reducers.append("documents_not_analyzed")
            return
        ctx.documents = self.evaluated(analysis, docs)
        if ctx.ticket.data.moment == Moment.QUOTE:  # "instalação de…" pode ser o que será feito: só registra a dúvida
            for d in ctx.documents:
                d.divergences = [x for x in d.divergences if not asks_for_after_service(x)]  # serviço ainda não feito: normal
                if d.service_status == Match.UNDETERMINED and d.solution and d.legible != Match.NO:
                    d.divergences.append("Não dá para saber pelo documento se o serviço já foi feito ou se é o que será feito")
        ctx.findings += self.flag(ctx.ticket, ctx.documents)
        ctx.findings += self.market_prices(ctx.documents, ctx.items)

    @staticmethod
    def ticket_documents(ticket: LoadedTicket, attachments: list[ClassifiedAttachment]) -> list[Attachment]:
        """Anexos que são documentos: PDFs e imagens identificadas como documento (termo, relatório, print de preço)."""
        doc_names = {a.name for a in attachments if a.category.value.endswith("_doc") and a.category not in NOT_DOCUMENTS}
        return [a for a in ticket.attachments if not a.is_spreadsheet and (a.content_type in DOC_TYPES or a.name in doc_names)]

    def analyze(
        self, session: LlmSession, ticket: LoadedTicket, scope: ScopeReading, items: list[EvaluatedItem], docs: list[Attachment]
    ) -> DocumentAnalysis:
        """Envia os documentos ao modelo principal com o chamado e os itens do orçamento (para ligar preços a itens)."""
        item_lines = "\n".join(f"{i.n}. {i.description} ({i.quantity:g} {i.unit} × {brl(i.unit_value)})" for i in items) or "(orçamento não lido)"
        content: list[Part] = [
            TextPart(
                f"{ticket.data.summary_text()}\n\nLEITURA DO ESCOPO:\n{ScopeStage.describe(scope)}\n\n"
                f"ITENS DO ORÇAMENTO:\n{item_lines}\n\n{len(docs)} documentos a seguir; use o número do anexo como 'index'."
            )
        ]
        for a in docs:
            content += attachment_parts(a, self.cfg.llm.image_max_side)
        meta = {"attachments": [a.name for a in docs], "indices": [a.index for a in docs]}
        return session.ask("documents", content, DocumentAnalysis, max_tokens=6000, meta=meta)

    @staticmethod
    def evaluated(analysis: DocumentAnalysis, docs: list[Attachment]) -> list[EvaluatedDocument]:
        by_index = {d.index: d for d in analysis.documents}
        out = []
        for a in docs:
            d = by_index.get(a.index)
            if d is None:
                out.append(EvaluatedDocument(file=a.name, legible=Match.UNDETERMINED, matches_ticket=Match.UNDETERMINED, reason="Documento não lido"))
                continue
            out.append(EvaluatedDocument(file=a.name, **d.model_dump(exclude={"index"})))
        return out

    def flag(self, ticket: LoadedTicket, docs: list[EvaluatedDocument]) -> list[Finding]:
        """Apontamentos a partir da leitura: ilegível, de outro chamado, data fora da janela do chamado e serviço já
        executado quando o chamado ainda está na aprovação do orçamento (só com prova explícita no documento)."""
        findings: list[Finding] = []
        dates = ticket.data.dates
        tol = timedelta(days=self.rubric.photo_date_tolerance_days)
        for d in docs:
            if d.legible == Match.NO:
                findings.append(self.scorer.finding("unreadable_document", d.reason or "Não foi possível ler o documento", d.file))
                continue
            if d.matches_ticket == Match.NO:
                why = "; ".join(d.divergences) or d.reason or "O documento não corresponde ao chamado"
                findings.append(self.scorer.finding("document_mismatch", why, d.file))
            when = parse_date(d.service_date)
            if when and (when < dates.opening - tol or when > dates.supplier_submission + tol):
                window = f"chamado aberto em {dates.opening:%d/%m/%Y} e enviado pelo fornecedor em {dates.supplier_submission:%d/%m/%Y}"
                evidence = f"Atendimento em {when:%d/%m/%Y}, fora da janela ({window})"
                findings.append(self.scorer.finding("document_date_inconsistent", evidence, d.file))
            done = ticket.data.moment == Moment.QUOTE and d.service_status == Match.YES
            if done and "service_before_approval" in self.rubric.finding_types and (not when or when <= dates.supplier_submission + tol):
                what = d.solution or "o serviço"
                quando = f" em {when:%d/%m/%Y}" if when else ""
                evidence = f"O documento afirma que {what[:1].lower() + what[1:]} já foi feito{quando}, antes da aprovação do orçamento"
                findings.append(self.scorer.finding("service_before_approval", evidence, d.file))
        return findings

    def market_prices(self, docs: list[EvaluatedDocument], items: list[EvaluatedItem]) -> list[Finding]:
        """Preço de mercado anexado (print de anúncio, cotação) abaixo do cobrado: apontamento sobre o excedente.

        Não repete o que a LPU já pegou: item com "preço acima da referência" fica de fora.
        """
        if "price_above_market" not in self.rubric.finding_types:
            return []
        tol = self.rubric.market_price_tolerance_pct / 100
        by_n = {i.n: i for i in items}
        out: list[Finding] = []
        for d in docs:
            for p in d.prices:
                item = by_n.get(p.quote_item)
                if item is None or p.value <= 0 or p.same_product == Match.NO or any(f.kind == "price_above_reference" for f in item.findings):
                    continue
                if item.unit_value > p.value * (1 + tol):
                    excess = round((item.unit_value - p.value) * item.quantity, 2)
                    pct = 100 * (item.unit_value / p.value - 1)
                    evidence = (
                        f"Item {item.n} cobrado a {brl(item.unit_value)}; o documento {d.file} mostra {p.description} a {brl(p.value)} "
                        f"({pct:.0f}% acima, tolerância {self.rubric.market_price_tolerance_pct:g}%)"
                    )
                    unsure = p.same_product != Match.YES  # sem especificação no orçamento, a comparação é indicativa
                    if unsure:
                        evidence = "Produto não confirmado (o orçamento não traz especificação para comparar). " + evidence
                    f = self.scorer.finding("price_above_market", evidence, f"item {item.n}: {item.description}", excess)
                    if unsure:
                        f = f.model_copy(update={"reduces_confidence": True})
                    item.findings.append(f)
                    item.amount_at_issue = amount_at_issue(item, item.findings, self.rubric)
                    out.append(f)
        return out
