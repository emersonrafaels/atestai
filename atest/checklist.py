"""Etapa 0 — checklist mínimo de evidências (regras em config/checklists.toml, por categoria do chamado).

- Orçamento: a planilha Excel padrão é lida por regra; se não abrir ou estiver fora do padrão, o item não é atendido.
- Fotos e documentos: o modelo rápido identifica cada anexo (categoria, momento, legibilidade).
- A decisão completo/incompleto é determinística, pelo checklist do tipo de serviço.
"""

from __future__ import annotations

from .analysis import AnalysisContext, AnalysisStage
from .attachments import attachment_parts
from .domain import (
    AttachmentCategory,
    ChecklistResult,
    ClassifiedAttachment,
    EvaluatedRequirement,
    PhotoMoment,
    Recommendation,
    Stage,
)
from .llm import LlmSession
from .llm_schemas import AttachmentIdentification
from .providers import Part, TextPart
from .repository import LoadedTicket, QuoteError, read_ticket_quote


class ChecklistStage(AnalysisStage):
    """Classifica os anexos e confere o checklist mínimo; se faltar evidência, encerra a análise e devolve ao fornecedor."""

    name = "checklist"
    progress = Stage.CHECKLIST

    def run(self, ctx: AnalysisContext) -> None:
        ctx.attachments = self.classify_attachments(ctx.session, ctx.ticket)
        ctx.checklist = result = self.evaluate(ctx.ticket, ctx.attachments)
        if not result.complete:
            ctx.halt = {
                "recommendation": Recommendation.CHECKLIST_RETURNED,
                "recommendation_reason": f"Checklist mínimo incompleto: {result.uploaded} de {result.total} itens obrigatórios",
                "summary": (
                    f"Devolvido: checklist mínimo incompleto ({result.uploaded} de {result.total}). "
                    "Sem score: o chamado não segue para a pessoa analista."
                ),
                "supplier_message": self.return_message(ctx.ticket, result),
            }

    # ------------------------------------------------------------------ classificação dos anexos
    def classify_attachments(self, session: LlmSession, ticket: LoadedTicket) -> list[ClassifiedAttachment]:
        """Planilhas são lidas por regra; fotos e documentos são identificados pelo modelo rápido."""
        result = {a.index: a for a in self._classify_spreadsheets(ticket)}
        others = [a for a in ticket.attachments if not a.is_spreadsheet]
        if others:
            result.update({a.index: a for a in self._classify_with_model(session, ticket, others)})
        return [result[i] for i in sorted(result)]

    @staticmethod
    def _classify_spreadsheets(ticket: LoadedTicket) -> list[ClassifiedAttachment]:
        out = []
        for a in ticket.spreadsheets:
            try:
                quote = read_ticket_quote(ticket, a)
                desc, ok = f"Orçamento {quote.number}: {len(quote.items)} itens, R$ {quote.total_value:,.2f}", True
            except QuoteError as e:
                desc, ok = f"Planilha fora do padrão: {e}", False
            out.append(
                ClassifiedAttachment(
                    index=a.index,
                    name=a.name,
                    category=AttachmentCategory.QUOTE_DOC,
                    moment=PhotoMoment.UNDETERMINED,
                    readable=ok,
                    short_description=desc,
                )
            )
        return out

    def _classify_with_model(self, session: LlmSession, ticket: LoadedTicket, others: list) -> list[ClassifiedAttachment]:
        categories = "\n".join(f"- {k}: {v}" for k, v in self.references.attachment_categories.items())
        content: list[Part] = [
            TextPart(
                f"{ticket.data.summary_text()}\n\nCATEGORIAS POSSÍVEIS:\n{categories}"
                f"\n\nA seguir, {len(others)} anexos. Identifique todos, usando o número do anexo como 'index'."
            )
        ]
        for a in others:
            content += attachment_parts(a, self.cfg.llm.image_max_side)
        resp = session.ask(
            "identify_attachments",
            content,
            AttachmentIdentification,
            fast=True,
            max_tokens=3000,
            meta={"attachments": [a.name for a in others], "indices": [a.index for a in others]},
        )
        by_index = {x.index: x for x in resp.attachments}
        out = []
        for a in others:
            x = by_index.get(a.index)
            out.append(
                ClassifiedAttachment(
                    index=a.index,
                    name=a.name,
                    category=x.category if x else AttachmentCategory.OTHER,
                    moment=x.moment if x else PhotoMoment.UNDETERMINED,
                    readable=x.readable if x else False,
                    short_description=x.short_description if x else "não identificado",
                )
            )
        return out

    # ------------------------------------------------------------------ regra do checklist
    def evaluate(self, ticket: LoadedTicket, attachments: list[ClassifiedAttachment]) -> ChecklistResult:
        """Confere cada item obrigatório do checklist contra os anexos legíveis da categoria aceita."""
        requirements = self.references.requirements(ticket.data)
        evaluated = []
        for r in requirements:
            matching = [a.name for a in attachments if a.category in r.accepted and a.readable]
            evaluated.append(EvaluatedRequirement(id=r.id, description=r.description, met=bool(matching), attachments=matching))
        missing = [r.id for r in evaluated if not r.met]
        return ChecklistResult(
            category=ticket.data.category,
            maintenance=ticket.data.maintenance_type,
            moment=ticket.data.moment,
            complete=bool(requirements) and not missing,
            uploaded=sum(r.met for r in evaluated),
            total=len(evaluated),
            requirements=evaluated,
            missing=missing,
        )

    @staticmethod
    def return_message(ticket: LoadedTicket, result: ChecklistResult) -> str:
        """Mensagem ao fornecedor listando as evidências que faltam."""
        shortfalls = [r.description[0].lower() + r.description[1:] for r in result.requirements if not r.met]
        name = ticket.data.supplier.name.rstrip(".")
        rows = [f"Olá, {name}. O chamado {ticket.id} foi devolvido porque faltam evidências obrigatórias para análise:"]
        rows += [f"- {s}{'.' if i == len(shortfalls) - 1 else ';'}" for i, s in enumerate(shortfalls)]
        rows.append("Reenvie os itens pelo próprio chamado.")
        return "\n".join(rows)
