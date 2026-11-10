"""Score de conformidade 0–100, faixas de recomendação e regras de trava, conforme a régua do deck.

Determinístico: o modelo não dá nota. Ele aponta divergências e a régua (config/rubric.toml) converte os
apontamentos em notas, score, confiança e recomendação.
"""

from __future__ import annotations

from pydantic import BaseModel

from .domain import Confidence, Finding, Grades, Recommendation, Rubric, ValidationResult
from .formatting import brl

# Motivo exibido para cada faixa de score (sem trava e com confiança suficiente).
BAND_REASONS = {
    Recommendation.APPROVE: "Score de 85 ou mais, sem travas",
    Recommendation.APPROVE_WITH_CAVEATS: "Score entre 70 e 84",
    Recommendation.RETURN_TO_SUPPLIER: "Score abaixo de 70, com apontamentos",
}

# Redutores de confiança que não são tipos de apontamento da régua (vêm das etapas), com o rótulo em português.
EXTRA_REDUCERS = {"unreadable_quote": "orçamento não lido"}


class ScoreResult(BaseModel):
    """Notas por validação, score ponderado, confiança e recomendação."""

    grades: Grades
    score: int
    confidence: Confidence
    confidence_reducers: list[str]
    recommendation: Recommendation
    recommendation_reason: str


class ScoreCalculator:
    """Aplica a régua: cria apontamentos tipados e converte a lista de apontamentos em score e recomendação."""

    def __init__(self, rubric: Rubric):
        self.rubric = rubric

    def finding(self, kind: str, evidence: str, reference: str = "", amount: float = 0.0) -> Finding:
        """Cria um apontamento do tipo `kind` com severidade, desconto, fase e trava definidos na régua."""
        spec = self.rubric.finding_types[kind]
        return Finding(
            kind=kind,
            validation=spec.validation,
            severity=spec.severity,
            discount=self.rubric.discount_by_severity[spec.severity],
            description=spec.description,
            evidence=evidence,
            reference=reference,
            lock=spec.lock,
            reduces_confidence=spec.reduces_confidence,
            phase=spec.phase,
            amount_at_issue=round(amount, 2),
        )

    def materiality_findings(self, amount_at_issue_pct: float, total: float = 0.0, amount: float = 0.0) -> list[Finding]:
        """Apontamento de valor relevante quando o valor potencial divergente passa do limite da régua.

        Cada tipo desconta uma vez por validação; sem isto, seis itens com o mesmo problema pesariam como um só,
        mesmo com o orçamento inteiro em questão.
        """
        limit = self.rubric.relevant_amount_at_issue_pct
        kind = "relevant_amount_at_issue"
        if kind not in self.rubric.finding_types or amount_at_issue_pct <= 0 or amount_at_issue_pct < limit:
            return []
        value = f" ({brl(amount)} de {brl(total)})" if total else ""
        evidence = f"{amount_at_issue_pct:.0f}% do orçamento em questão{value}, acima do limite de {limit:g}%"
        return [self.finding(kind, evidence, "orçamento")]

    def expected(self, kinds: list[str], amount_at_issue_pct: float = 0.0) -> tuple[list[str], ScoreResult]:
        """Gabarito: tipos esperados (com o de valor relevante, se couber) e o resultado da régua para eles."""
        base = [k for k in kinds if k != "relevant_amount_at_issue"]
        findings = [self.finding(k, "") for k in base] + self.materiality_findings(amount_at_issue_pct)
        return sorted({f.kind for f in findings}), self.compute(findings)

    def reducer_label(self, kind: str) -> str:
        """Rótulo em português de um redutor de confiança (tipo da régua ou redutor extra das etapas)."""
        spec = self.rubric.finding_types.get(kind)
        text = spec.description if spec else EXTRA_REDUCERS.get(kind, kind.replace("_", " "))
        return text[:1].lower() + text[1:]

    @staticmethod
    def filter_phase(findings: list[Finding], phase: int) -> list[Finding]:
        """Mantém só os apontamentos que valem na fase configurada da régua."""
        return [f for f in findings if f.phase <= phase]

    def absorbers(self, findings: list[Finding]) -> dict[tuple[str, str], str]:
        """(validação, tipo absorvido) → tipo que absorve, para os tipos presentes nos apontamentos.

        Ex.: `missing_after_photo` absorve `photo_mismatch`: a foto de outro ambiente e a falta da foto do depois
        costumam ser o mesmo problema; descontar os dois puniria duas vezes.
        """
        present = {(f.validation.value, f.kind) for f in findings}
        out: dict[tuple[str, str], str] = {}
        for validation, kind in sorted(present):
            spec = self.rubric.finding_types.get(kind)
            for absorbed in spec.absorbs if spec else []:
                if absorbed != kind and (validation, absorbed) in present:
                    out.setdefault((validation, absorbed), kind)
        return out

    def mark_absorbed(self, findings: list[Finding]) -> list[Finding]:
        """Cópias dos apontamentos com `absorbed_by` preenchido (para o parecer e o painel)."""
        by = self.absorbers(findings)
        return [f.model_copy(update={"absorbed_by": by.get((f.validation.value, f.kind), "")}) for f in findings]

    def compute(self, findings: list[Finding], extra_reducers: list[str] | None = None) -> ScoreResult:
        """Notas, score, confiança e recomendação a partir dos apontamentos.

        Cada tipo desconta uma vez por validação (como no simulador do deck); todos seguem listados como evidência.
        Tipos absorvidos por outro presente na mesma validação (`absorbs` na régua) não descontam.
        """
        grades = self._grades(findings)
        score = round(sum(grades[v] * self.rubric.weights[v] for v in ValidationResult) / sum(self.rubric.weights.values()))
        reducers = sorted({f.kind for f in findings if f.reduces_confidence} | set(extra_reducers or []))
        confidence = self._confidence(len(reducers))
        recommendation, reason = self._recommendation(findings, score, confidence, reducers)
        return ScoreResult(
            grades=Grades(**{v.value: n for v, n in grades.items()}),
            score=score,
            confidence=confidence,
            confidence_reducers=reducers,
            recommendation=recommendation,
            recommendation_reason=reason,
        )

    def _grades(self, findings: list[Finding]) -> dict[ValidationResult, int]:
        discounts: dict[ValidationResult, dict[str, int]] = {v: {} for v in ValidationResult}
        absorbed = self.absorbers(findings)
        for f in findings:
            if (f.validation.value, f.kind) not in absorbed:
                discounts[f.validation][f.kind] = f.discount
        return {v: max(0, 100 - sum(discounts[v].values())) for v in ValidationResult}

    def _confidence(self, n_reducers: int) -> Confidence:
        if n_reducers >= self.rubric.confidence.low_with_n_reducers:
            return Confidence.LOW
        if n_reducers >= self.rubric.confidence.medium_with_n_reducers:
            return Confidence.MEDIUM
        return Confidence.HIGH

    def _recommendation(self, findings: list[Finding], score: int, confidence: Confidence, reducers: list[str]) -> tuple[Recommendation, str]:
        locks = [f for f in findings if f.lock]
        if locks:  # trava de integridade vence qualquer nota
            return Recommendation.RETURN_LOCKED, f"Trava de integridade: {locks[0].description.lower()}. Devolver qualquer que seja a nota"
        if confidence == Confidence.LOW:
            labels = "; ".join(self.reducer_label(r) for r in reducers)
            return Recommendation.DETAILED_REVIEW, f"Confiança baixa ({labels}): entrada insuficiente para concluir"
        band = next(b for b in sorted(self.rubric.bands, key=lambda b: -b.score_min) if score >= b.score_min)
        reason = BAND_REASONS[band.recommendation]
        if confidence == Confidence.MEDIUM:
            reason += "; confiança média: revisar com atenção"
        return band.recommendation, reason
