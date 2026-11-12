"""Parecer explicável: resumo para a pessoa analista e apontamentos sugeridos ao fornecedor."""

from __future__ import annotations

import logging
from typing import Any

from .analysis import AnalysisContext, AnalysisStage
from .domain import Confidence, Recommendation, Severity, Stage, ValidationResult
from .formatting import brl
from .llm_schemas import AssessmentText
from .providers import TextPart

log = logging.getLogger(__name__)

# Ação sugerida ao fornecedor por tipo de apontamento ({ref} = item, foto ou planilha citada).
SUPPLIER_ACTIONS = {
    "out_of_scope_item": "remover o {ref}, que está fora do escopo",
    "unjustified_replacement": "enviar laudo técnico que justifique o {ref}",
    "quantity_above_expected": "justificar ou ajustar a quantidade do {ref}",
    "price_above_reference": "ajustar o preço do {ref} à referência",
    "duplicate_item": "remover a cobrança duplicada do {ref}",
    "photo_mismatch": "substituir as fotos que não mostram o ambiente do escopo",
    "missing_after_photo": "enviar foto que comprove o serviço concluído",
    "missing_before_photo": "enviar foto do estado anterior ao serviço",
    "unreadable_photo": "reenviar a foto ilegível ({ref})",
    "reused_photo": "enviar fotos originais deste chamado",
    "photo_dated_before": "enviar fotos tiradas durante a execução deste chamado",
    "spreadsheet_mismatch": "corrigir a planilha para refletir o chamado ({ref})",
    "inconsistent_scope": "confirmar com a agência a categoria e o sintoma do chamado",
    "vague_scope": "confirmar com a agência o equipamento, o local e o serviço pedidos",
    "after_photo_unconfirmed_location": "enviar foto do serviço concluído que mostre o ambiente do escopo",
    "unverifiable_quantity": "informar quantos equipamentos foram atendidos e enviar evidência de cada um ({ref})",
    "item_without_photo": "enviar fotos que evidenciem o que foi cobrado ({ref})",
    "relevant_amount_at_issue": "revisar o orçamento: a maior parte do valor está em questão",
}


class AssessmentWriter:
    """Redige o parecer: pelo modelo rápido (modo API) ou por regra (simulado ou falha na redação)."""

    @staticmethod
    def prompt(result: dict[str, Any]) -> str:
        """Resultado da régua em texto, para o modelo redigir o parecer (em português)."""
        findings = (
            "\n".join(
                f"- [{ValidationResult(f['validation']).label} / severidade {Severity(f['severity']).label}] {f['description']}: {f['evidence']}"
                + (f" ({f['reference']})" if f["reference"] else "")
                for f in result["findings"]
            )
            or "- nenhum"
        )
        grades = ", ".join(f"{ValidationResult(k).label} {v}" for k, v in (result["grades"] or {}).items())
        return (
            f"RECOMENDAÇÃO: {Recommendation(result['recommendation']).label}. {result['recommendation_reason']}\n"
            f"Score: {result['score']} | Notas: {grades} | Confiança: {Confidence(result['confidence']).label}\n"
            f"Valor potencial divergente: {brl(result['amount_at_issue'])} ({result['amount_at_issue_pct']:.0f}% do orçamento)\n"
            f"APONTAMENTOS:\n{findings}"
            + ("\n\nOBSERVAÇÕES DAS ETAPAS (não pontuadas):\n" + "\n".join(f"- {o}" for o in result.get("observations") or [])
               if result.get("observations") else "")
        )

    @staticmethod
    def from_template(result: dict[str, Any]) -> AssessmentText:
        """Parecer por regra, sem modelo."""
        rec = Recommendation(result["recommendation"])
        findings = result["findings"]
        parts = [f"{rec.label}. {result['recommendation_reason']}."]
        if findings:
            examples = "; ".join(f"{f['description'].lower()} ({f['reference'] or f['evidence']})" for f in findings[:4])
            parts.append(f"{len(findings)} apontamento(s): {examples}.")
        if result["amount_at_issue"]:
            parts.append(f"Valor potencial divergente: {brl(result['amount_at_issue'])} ({result['amount_at_issue_pct']:.0f}% do orçamento).")
        if obs := result.get("observations"):
            parts.append(f"Atenção: {obs[0]}")
        message = ""
        needs_action = rec in (Recommendation.RETURN_TO_SUPPLIER, Recommendation.RETURN_LOCKED, Recommendation.APPROVE_WITH_CAVEATS)
        if needs_action and findings:
            actions = [SUPPLIER_ACTIONS[f["kind"]].format(ref=f["reference"] or "item") for f in findings if f["kind"] in SUPPLIER_ACTIONS]
            message = "; ".join(dict.fromkeys(actions)) + "."
            message = message[0].upper() + message[1:]
        return AssessmentText(summary=" ".join(parts), supplier_message=message)


class AssessmentStage(AnalysisStage):
    """Última etapa: redação do parecer. A redação nunca derruba o parecer (cai para o texto por regra)."""

    name = "assessment"
    progress = Stage.ASSESSMENT

    def run(self, ctx: AnalysisContext) -> None:
        result = ctx.scoring_input()
        text = f"{ctx.ticket.data.summary_text()}\n\n{AssessmentWriter.prompt(result)}"
        try:
            ctx.text = ctx.session.ask("assessment", [TextPart(text)], AssessmentText, fast=True, max_tokens=1200, meta={"result": result})
        except Exception:
            log.exception("falha ao redigir o parecer; usando o texto por regra")
            ctx.text = AssessmentWriter.from_template(result)
