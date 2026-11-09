"""Validação 1 — Escopo: o que exatamente foi pedido?"""

from __future__ import annotations

from .analysis import AnalysisContext, AnalysisStage
from .domain import Stage
from .llm_schemas import ScopeReading
from .providers import TextPart


class ScopeStage(AnalysisStage):
    """Lê o escopo em linguagem natural e aponta escopo vago ou incoerente com a categoria e o sintoma."""

    name = "scope"
    progress = Stage.SCOPE

    def run(self, ctx: AnalysisContext) -> None:
        ticket = ctx.ticket.data
        reading = ctx.session.ask("scope", [TextPart(ticket.summary_text())], ScopeReading, max_tokens=2500)
        ctx.scope = reading
        if reading.vague_scope:
            ctx.findings.append(self.scorer.finding("vague_scope", reading.vague_reason or "Escopo sem definição suficiente", "escopo"))
        if not reading.consistent_with_category_symptom:
            label = f"{ticket.category.label} / {ticket.symptom.label}"
            evidence = reading.coherence_note or f"Escopo não combina com {label}"
            ctx.findings.append(self.scorer.finding("inconsistent_scope", evidence, label))

    @staticmethod
    def describe(reading: ScopeReading) -> str:
        """Resumo da leitura do escopo, em português, para os prompts das etapas seguintes."""
        quantities = "; ".join(f"{q.quantity:g} {q.unit} {q.description}" for q in reading.mentioned_quantities) or "nenhuma"
        return (
            f"Local: {reading.local} | Ambiente: {reading.environment} | Equipamento: {reading.equipment or '-'}\n"
            f"Serviços pedidos: {'; '.join(reading.requested_services)}\n"
            f"Quantidades mencionadas: {quantities}\n"
            "Critérios de aceite:\n" + "\n".join(f"- {c}" for c in reading.acceptance_criteria) + "\n"
            "Evidências esperadas:\n" + "\n".join(f"- {c}" for c in reading.expected_evidence) + "\n"
            f"Foto do 'antes' aplicável: {'sim' if reading.before_evidence_applicable else 'não'}"
        )
