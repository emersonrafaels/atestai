"""Score de conformidade 0–100, faixas de recomendação e regras de trava, conforme a régua do deck.

Determinístico: o modelo não dá nota. Ele aponta divergências e a régua (config/rubric.toml) converte os
apontamentos em notas, score, confiança e recomendação.
"""

from __future__ import annotations

from pydantic import BaseModel

from .domain import Confidence, Finding, Grades, Recommendation, Rubric, ValidationResult

# Motivo exibido para cada faixa de score (sem trava e com confiança suficiente).
BAND_REASONS = {
    Recommendation.APPROVE: "Score de 85 ou mais, sem travas",
    Recommendation.APPROVE_WITH_CAVEATS: "Score entre 70 e 84",
    Recommendation.RETURN_TO_SUPPLIER: "Score abaixo de 70, com apontamentos",
}


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

    @staticmethod
    def filter_phase(findings: list[Finding], phase: int) -> list[Finding]:
        """Mantém só os apontamentos que valem na fase configurada da régua."""
        return [f for f in findings if f.phase <= phase]

    def compute(self, findings: list[Finding], extra_reducers: list[str] | None = None) -> ScoreResult:
        """Notas, score, confiança e recomendação a partir dos apontamentos.

        Cada tipo desconta uma vez por validação (como no simulador do deck); todos seguem listados como evidência.
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
        for f in findings:
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
            return Recommendation.DETAILED_REVIEW, f"Confiança baixa ({', '.join(reducers)}): entrada insuficiente para concluir"
        band = next(b for b in sorted(self.rubric.bands, key=lambda b: -b.score_min) if score >= b.score_min)
        reason = BAND_REASONS[band.recommendation]
        if confidence == Confidence.MEDIUM:
            reason += "; confiança média: revisar com atenção"
        return band.recommendation, reason
