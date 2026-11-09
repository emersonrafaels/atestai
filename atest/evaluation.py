"""Compara pareceres com o gabarito do dataset (o backtest em miniatura).

Métricas: concordância da recomendação (exata e "direção": segue × para), checklist,
precisão/cobertura dos apontamentos por tipo (opcionais do gabarito não contam como erro) e erro médio do score.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

from .domain import Assessment, Recommendation
from .repository import GroundTruth, load_ground_truth


class TicketComparison(BaseModel):
    """Um chamado: o que o gabarito esperava e o que o Atest.AI concluiu."""

    ticket_id: str
    expected: Recommendation
    obtained: Recommendation
    expected_score: int | None
    obtained_score: int | None
    recommendation_ok: bool
    direction_ok: bool
    checklist_ok: bool
    missed: list[str]
    extra: list[str]


class KindCount(BaseModel):
    """Verdadeiros positivos, falsos positivos e falsos negativos de um tipo de apontamento."""

    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None


class Evaluation(BaseModel):
    """Resumo da comparação de uma rodada com o gabarito."""

    n: int
    exact_recommendation: int
    direction: int
    checklist: int
    avg_score_error: float | None
    by_kind: dict[str, KindCount]
    by_ticket: list[TicketComparison]

    def render(self) -> str:
        """Tabela chamado a chamado e totais, para o terminal."""
        lines = [f"\n{'ticket':<10} {'esperado':<22} {'obtido':<22} {'score':>11}"]
        for c in self.by_ticket:
            score = f"{c.expected_score if c.expected_score is not None else '-':>3} → {c.obtained_score if c.obtained_score is not None else '-':>3}"
            extra = (f" faltou {c.missed}" if c.missed else "") + (f" sobrou {c.extra}" if c.extra else "")
            lines.append(f"{c.ticket_id:<10} {c.expected.value:<22} {c.obtained.value:<22} {score:>11}  {'✓' if c.recommendation_ok else '✗'}{extra}")
        n = self.n or 1
        lines.append(
            f"\nRecomendação exata {self.exact_recommendation}/{self.n} ({100 * self.exact_recommendation / n:.0f}%) · "
            f"direção {self.direction}/{self.n} · checklist {self.checklist}/{self.n}"
            + (f" · erro médio do score {self.avg_score_error:.1f}" if self.avg_score_error is not None else "")
        )
        for kind, c in self.by_kind.items():
            p = f"{c.precision:.0%}" if c.precision is not None else "  -"
            r = f"{c.recall:.0%}" if c.recall is not None else "  -"
            lines.append(f"  {kind:<26} VP {c.tp:>2}  FP {c.fp:>2}  FN {c.fn:>2}   precisão {p:>4}  cobertura {r:>4}")
        return "\n".join(lines)


class GroundTruthEvaluator:
    """Compara pareceres com os arquivos de gabarito de uma pasta."""

    def __init__(self, ground_truth_dir: Path):
        self.ground_truth_dir = Path(ground_truth_dir)

    def compare(self, assessment: Assessment, gt: GroundTruth | None = None) -> TicketComparison | None:
        """Compara um parecer com o gabarito do chamado; None se não houver gabarito."""
        g = gt or load_ground_truth(self.ground_truth_dir, assessment.ticket_id)
        if g is None:
            return None
        flagged = {f.kind for f in assessment.findings}
        wanted, optional = set(g.findings), set(g.optional)
        checklist = assessment.checklist
        return TicketComparison(
            ticket_id=assessment.ticket_id,
            expected=g.recommendation,
            obtained=assessment.recommendation,
            expected_score=g.score,
            obtained_score=assessment.score,
            recommendation_ok=assessment.recommendation == g.recommendation,
            direction_ok=assessment.recommendation.proceeds == g.recommendation.proceeds,
            checklist_ok=checklist is not None and checklist.complete == g.checklist_ok and set(checklist.missing) == set(g.missing),
            missed=sorted(wanted - flagged),
            extra=sorted((flagged - wanted) - optional),
        )

    def evaluate(self, assessments: list[Assessment]) -> Evaluation:
        """Compara todos os pareceres e agrega as métricas."""
        by_kind: dict[str, KindCount] = defaultdict(KindCount)
        comparisons, errors = [], []
        for p in assessments:
            g = load_ground_truth(self.ground_truth_dir, p.ticket_id)
            c = self.compare(p, g)
            if c is None or g is None:
                continue
            comparisons.append(c)
            flagged = {f.kind for f in p.findings}
            for kind in flagged | set(g.findings):
                if kind in flagged and kind in g.findings:
                    by_kind[kind].tp += 1
                elif kind in flagged and kind not in g.optional:
                    by_kind[kind].fp += 1
                elif kind not in flagged:
                    by_kind[kind].fn += 1
            if c.expected_score is not None and c.obtained_score is not None:
                errors.append(abs(c.expected_score - c.obtained_score))
        return Evaluation(
            n=len(comparisons),
            exact_recommendation=sum(c.recommendation_ok for c in comparisons),
            direction=sum(c.direction_ok for c in comparisons),
            checklist=sum(c.checklist_ok for c in comparisons),
            avg_score_error=(sum(errors) / len(errors)) if errors else None,
            by_kind=dict(sorted(by_kind.items())),
            by_ticket=comparisons,
        )
