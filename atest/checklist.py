"""Etapa 0 — checklist mínimo de evidências (regras em config/checklists.toml, por categoria do chamado).

- Orçamento: a planilha Excel padrão é lida por regra; se não abrir ou estiver fora do padrão, o item não é atendido.
- Fotos e documentos: o modelo rápido identifica cada anexo (categoria, momento, legibilidade).
- A decisão completo/incompleto é determinística, pelo checklist do tipo de serviço.
"""

from __future__ import annotations

import logging

from .analysis import AnalysisContext, AnalysisStage
from .attachments import attachment_parts, chunked
from .domain import (
    AttachmentCategory,
    ChecklistResult,
    ClassifiedAttachment,
    EvaluatedRequirement,
    PhotoMoment,
    Recommendation,
    Stage,
)
from .llm import MAX_OUTPUT_TOKENS, LlmSession, LlmTimeout
from .llm_schemas import AttachmentIdentification, IdentifiedAttachment
from .observability import event
from .providers import Part, ProviderError, TextPart
from .repository import LoadedTicket, QuoteError, read_ticket_quote


class ChecklistStage(AnalysisStage):
    """Classifica os anexos e confere o checklist mínimo; se faltar evidência, encerra a análise e devolve ao fornecedor."""

    name = "checklist"
    progress = Stage.CHECKLIST

    def run(self, ctx: AnalysisContext) -> None:
        """Preenche `ctx.attachments` e `ctx.checklist`; com checklist incompleto, preenche `ctx.halt` com a
        recomendação "checklist devolvido", o resumo e a mensagem ao fornecedor (a análise para aqui, sem score).
        """
        # 1. Identifica cada anexo (orçamento, foto do antes/depois, termo, relatório...) e se está legível.
        ctx.attachments = self.classify_attachments(ctx.session, ctx.ticket)
        # 2. Confere, por regra, se os anexos cobrem os itens obrigatórios do tipo de serviço.
        ctx.checklist = result = self.evaluate(ctx.ticket, ctx.attachments)
        # 3. Faltou evidência: encerra a análise aqui e devolve ao fornecedor (sem score).
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
    def classify_attachments(
        self, session: LlmSession, ticket: LoadedTicket
    ) -> list[ClassifiedAttachment]:
        """Planilhas são lidas por regra; fotos e documentos são identificados pelo modelo rápido.

        Args:
            session: sessão de LLM do chamado.
            ticket: chamado com os anexos numerados.

        Returns:
            Um `ClassifiedAttachment` por anexo, na ordem do número do anexo. Planilha que não abre ou está fora do
            padrão fica como ilegível; anexo que o modelo não identificou fica como "outro" e ilegível.
        """
        # Planilhas: lidas por regra, sem custo de modelo (número do anexo → classificação).
        result = {a.index: a for a in self._classify_spreadsheets(ticket)}
        # Fotos, PDFs e demais anexos: identificados pelo modelo rápido, numa chamada só.
        others = [a for a in ticket.attachments if not a.is_spreadsheet]
        if others:
            result.update(
                {a.index: a for a in self._classify_with_model(session, ticket, others)}
            )
        # Devolve na ordem do número do anexo.
        return [result[i] for i in sorted(result)]

    @staticmethod
    def _classify_spreadsheets(ticket: LoadedTicket) -> list[ClassifiedAttachment]:
        """Planilhas viram "orçamento": legível se abriu no padrão, ilegível (com o motivo) se não."""
        out = []
        for a in ticket.spreadsheets:
            # Tenta ler o orçamento; a descrição resume o que foi lido ou explica por que falhou.
            try:
                quote = read_ticket_quote(ticket, a)
                desc, ok = (
                    f"Orçamento {quote.number}: {len(quote.items)} itens, R$ {quote.total_value:,.2f}",
                    True,
                )
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

    def _classify_with_model(
        self, session: LlmSession, ticket: LoadedTicket, others: list
    ) -> list[ClassifiedAttachment]:
        """Identifica fotos e documentos com o modelo rápido, em lotes de até [llm.max_images_per_call] anexos.

        Chamado com muitas fotos (ex.: 100+) numa chamada só estourava o limite de tokens de saída; em lotes, cada
        resposta é pequena. Lote que falha é dividido ao meio e tentado de novo (até MIN_CHUNK anexos).

        Args:
            session: sessão de LLM do chamado.
            ticket: chamado (o resumo vai no pedido).
            others: anexos que não são planilha.

        Returns:
            Um `ClassifiedAttachment` por anexo; o que o modelo não devolveu fica como "outro", ilegível.

        Raises:
            ProviderError: um lote falhou mesmo dividido no tamanho mínimo (marcar os anexos como "não identificado"
                devolveria o chamado ao fornecedor sem motivo real).
        """
        chunks = chunked(others, self.cfg.llm.max_images_per_call)
        if len(chunks) > 1:
            event("attachments_chunked", attachments=len(others), chunks=len(chunks))
        identified: list[IdentifiedAttachment] = []
        for n, chunk in enumerate(chunks, 1):
            identified += self._identify_resilient(
                session, ticket, chunk, (n, len(chunks)) if len(chunks) > 1 else None
            )
        # Liga a resposta ao anexo pelo número; anexo esquecido pelo modelo cai no padrão "não identificado".
        by_index = {x.index: x for x in identified}
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

    MIN_CHUNK = 6  # menor lote ao dividir um lote que falhou

    def _identify_resilient(
        self,
        session: LlmSession,
        ticket: LoadedTicket,
        chunk: list,
        batch: tuple[int, int] | None,
    ) -> list[IdentifiedAttachment]:
        """Identifica um lote; se falhar (resposta cortada ou fora do formato), divide ao meio e tenta cada metade.

        Raises:
            ProviderError: o lote já está no tamanho mínimo (ou a API travou) e mesmo assim falhou.
        """
        try:
            return self._identify_chunk(session, ticket, chunk, batch)
        except ProviderError as e:
            # Lote pequeno ou API travada: dividir não resolve (só multiplicaria a espera).
            if len(chunk) <= self.MIN_CHUNK or isinstance(e, LlmTimeout):
                raise
            event(
                "attachments_split",
                logging.WARNING,
                error=str(e)[:300],
                attachments=len(chunk),
            )
        half = (len(chunk) + 1) // 2
        return self._identify_resilient(
            session, ticket, chunk[:half], batch
        ) + self._identify_resilient(session, ticket, chunk[half:], batch)

    def _identify_chunk(
        self,
        session: LlmSession,
        ticket: LoadedTicket,
        chunk: list,
        batch: tuple[int, int] | None = None,
    ) -> list[IdentifiedAttachment]:
        """Uma chamada ao modelo rápido para identificar um lote de anexos.

        Os argumentos passados ao session.ask:
            task: "identify_attachments" (prompt de sistema em config/prompts.toml).
            parts: resumo do chamado + categorias possíveis + o conteúdo de cada anexo (imagem ou PDF).
            output: `AttachmentIdentification`, uma identificação por anexo.
            fast: True, usa o modelo rápido (tarefa simples, muitas imagens).
            max_tokens: 600 + 120 por anexo (20 anexos ≈ 3000), até MAX_OUTPUT_TOKENS.
            meta: nomes e números dos anexos enviados, para o rastro.
        """
        # Categorias aceitas (config/checklists.toml), listadas no pedido para o modelo escolher uma.
        categories = "\n".join(
            f"- {k}: {v}" for k, v in self.references.attachment_categories.items()
        )
        part = (
            f"Lote {batch[0]} de {batch[1]} dos anexos do chamado: identifique só estes. "
            if batch
            else ""
        )
        content: list[Part] = [
            TextPart(
                f"{ticket.data.summary_text()}\n\nCATEGORIAS POSSÍVEIS:\n{categories}"
                f"\n\n{part}A seguir, {len(chunk)} anexos. Identifique todos, usando o número do anexo como 'index'."
            )
        ]
        # Cada anexo vai como imagem (reduzida a [llm.image_max_side]) ou PDF, precedido do rótulo "Anexo N".
        for a in chunk:
            content += attachment_parts(a, self.cfg.llm.image_max_side)
        resp = session.ask(
            "identify_attachments",
            content,
            AttachmentIdentification,
            fast=True,
            max_tokens=min(MAX_OUTPUT_TOKENS, 600 + 120 * len(chunk)),
            meta={
                "attachments": [a.name for a in chunk],
                "indices": [a.index for a in chunk],
            },
        )
        return resp.attachments

    # ------------------------------------------------------------------ regra do checklist
    def evaluate(
        self, ticket: LoadedTicket, attachments: list[ClassifiedAttachment]
    ) -> ChecklistResult:
        """Confere cada item obrigatório do checklist contra os anexos legíveis da categoria aceita.

        Args:
            ticket: chamado (categoria, tipo de manutenção, etapa e esteira escolhem a regra do checklist).
            attachments: anexos já classificados.

        Returns:
            O resultado do checklist: itens atendidos e faltantes, contagem e `complete` (True só se há regra
            para o chamado e nada falta).
        """
        # Regra do checklist para este chamado (categoria × tipo de manutenção × etapa × esteira).
        requirements = self.references.requirements(ticket.data)
        evaluated = []
        for r in requirements:
            # Um item é atendido se ao menos um anexo legível tem uma das categorias aceitas por ele.
            matching = [
                a.name for a in attachments if a.category in r.accepted and a.readable
            ]
            evaluated.append(
                EvaluatedRequirement(
                    id=r.id,
                    description=r.description,
                    met=bool(matching),
                    attachments=matching,
                )
            )
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
        """Mensagem ao fornecedor listando as evidências que faltam.

        Args:
            ticket: chamado (id e nome do fornecedor).
            result: resultado do checklist com os itens não atendidos.

        Returns:
            Texto com saudação, uma linha por evidência faltante e o pedido de reenvio.
        """
        shortfalls = [
            r.description[0].lower() + r.description[1:]
            for r in result.requirements
            if not r.met
        ]
        name = ticket.data.supplier.name.rstrip(".")
        rows = [
            f"Olá, {name}. O chamado {ticket.id} foi devolvido porque faltam evidências obrigatórias para análise:"
        ]
        rows += [
            f"- {s}{'.' if i == len(shortfalls) - 1 else ';'}"
            for i, s in enumerate(shortfalls)
        ]
        rows.append("Reenvie os itens pelo próprio chamado.")
        return "\n".join(rows)
