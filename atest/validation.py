"""Métricas de validação (visão de ciência de dados) de uma rodada contra o gabarito.

- Recomendação: matriz de confusão, acurácia com IC 95% (bootstrap), kappa de Cohen, acurácia balanceada.
- "Pegar problema" (binário: o chamado deveria parar?): precisão, cobertura (recall), F1 e especificidade.
- Apontamentos: precisão, cobertura e F1 por tipo; micro e macro F1. Opcionais do gabarito não contam como erro.
- Score: erro absoluto médio, RMSE, viés e correlação de Pearson; pares para o gráfico de dispersão.
- Recortes por categoria e por modelo de serviço; valor em questão; operação (latência e custo p50/p95).
- Portão de qualidade: limites de config/settings.toml [validation].
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from .config import Settings
from .domain import Assessment, Recommendation
from .repository import GroundTruth, list_tickets, load_ground_truth, load_ticket

# Ordem das classes na matriz de confusão e nos gráficos.
CLASSES = [
    r.value
    for r in (
        Recommendation.APPROVE,
        Recommendation.APPROVE_WITH_CAVEATS,
        Recommendation.DETAILED_REVIEW,
        Recommendation.RETURN_TO_SUPPLIER,
        Recommendation.RETURN_LOCKED,
        Recommendation.CHECKLIST_RETURNED,
    )
]


# ============================================================================ modelos do relatório
class Interval(BaseModel):
    """Valor com intervalo de confiança de 95%."""

    value: float
    ci_low: float
    ci_high: float


class BinaryMetric(BaseModel):
    """Matriz 2×2 e métricas derivadas."""

    tp: int
    fp: int
    fn: int
    tn: int
    precision: float | None
    recall: float | None
    f1: float | None
    specificity: float | None


class FindingMetric(BaseModel):
    """Precisão, cobertura e F1 de um tipo de apontamento."""

    kind: str
    support: int
    tp: int
    fp: int
    fn: int
    precision: float | None
    recall: float | None
    f1: float | None


class ScorePair(BaseModel):
    """Score esperado e obtido de um chamado (gráfico de dispersão)."""

    ticket_id: str
    expected: int
    obtained: int


class Segment(BaseModel):
    """Acurácia em um recorte (categoria ou modelo de serviço)."""

    name: str
    n: int
    hits: int
    accuracy: float


class MismatchCase(BaseModel):
    """Chamado em que a recomendação divergiu do gabarito."""

    ticket_id: str
    category: str
    expected: str
    obtained: str
    expected_score: int | None
    obtained_score: int | None
    missed: list[str]
    extra: list[str]


class Operations(BaseModel):
    """Latência, custo e tokens da rodada."""

    latency_p50_s: float | None
    latency_p95_s: float | None
    avg_cost_brl: float
    p95_cost_brl: float
    total_cost_brl: float
    avg_input_tokens: float
    avg_output_tokens: float


class GateItem(BaseModel):
    """Um critério do portão de qualidade."""

    metric: str
    value: float | None
    limit: float
    direction: str  # ">=" ou "<="
    passed: bool


class ValidationReport(BaseModel):
    """Relatório de validação de uma rodada contra o gabarito."""

    n: int
    no_ground_truth: int
    classes: list[str] = CLASSES
    matrix: list[list[int]] = Field(description="linhas = esperado, colunas = obtido, na ordem de `classes`")
    accuracy: Interval
    balanced_accuracy: float
    kappa: float | None
    problem_catch: BinaryMetric
    problem_catch_f1_ci: Interval | None
    checklist_accuracy: float
    findings: list[FindingMetric]
    findings_micro: BinaryMetric
    finding_macro_f1: float | None
    score_pairs: list[ScorePair]
    score_mae: float | None
    score_rmse: float | None
    score_bias: float | None
    score_pearson: float | None
    expected_amount_at_issue: float
    obtained_amount_at_issue: float
    amount_at_issue_mae: float | None
    by_category: list[Segment]
    by_service_template: list[Segment]
    operations: Operations
    mismatches: list[MismatchCase]
    gate: list[GateItem]
    gate_passed: bool

    def render(self) -> str:
        """Resumo em texto para o terminal."""
        pct = lambda x: "—" if x is None else f"{100 * x:.1f}%"  # noqa: E731
        pc = self.problem_catch
        lines = [
            f"\nValidação em {self.n} chamados ({self.no_ground_truth} sem gabarito)",
            f"  Acurácia {pct(self.accuracy.value)} (IC95% {pct(self.accuracy.ci_low)}–{pct(self.accuracy.ci_high)})"
            f" · balanceada {pct(self.balanced_accuracy)}" + (f" · kappa {self.kappa:.3f}" if self.kappa is not None else ""),
            f"  Pegar problema: precisão {pct(pc.precision)} · cobertura {pct(pc.recall)} · F1 {pct(pc.f1)} · especificidade {pct(pc.specificity)}",
            f"  Apontamentos: F1 micro {pct(self.findings_micro.f1)} · F1 macro {pct(self.finding_macro_f1)}",
        ]
        if self.score_mae is not None:
            lines.append(
                f"  Score: MAE {self.score_mae:.1f} · RMSE {self.score_rmse:.1f} · viés {self.score_bias:+.1f}"
                f" · Pearson {self.score_pearson or 0:.3f}"
            )
        lines += ["\n  Matriz de confusão (linhas = esperado, colunas = obtido)", "  " + " " * 24 + "".join(f"{c[:9]:>10}" for c in self.classes)]
        lines += [f"  {c:<24}" + "".join(f"{x:>10}" for x in row) for c, row in zip(self.classes, self.matrix, strict=True)]
        lines.append("\n  Portão de qualidade:")
        for g in self.gate:
            value = "—" if g.value is None else f"{g.value:.3f}"
            lines.append(f"    {'✓' if g.passed else '✗'} {g.metric:<30} {value:>8} {g.direction} {g.limit}")
        lines.append(f"  → {'APROVADO' if self.gate_passed else 'REPROVADO'}")
        return "\n".join(lines)


# ============================================================================ estatística
class Stats:
    """Funções estatísticas usadas no relatório (sem dependências além da biblioteca padrão)."""

    @staticmethod
    def div(a: float, b: float) -> float | None:
        return a / b if b else None

    @staticmethod
    def f1(precision: float | None, recall: float | None) -> float | None:
        if precision is None or recall is None:
            return None
        return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)

    @classmethod
    def binary(cls, tp: int, fp: int, fn: int, tn: int) -> BinaryMetric:
        p, r = cls.div(tp, tp + fp), cls.div(tp, tp + fn)
        return BinaryMetric(tp=tp, fp=fp, fn=fn, tn=tn, precision=p, recall=r, f1=cls.f1(p, r), specificity=cls.div(tn, tn + fp))

    @staticmethod
    def percentile(xs: Sequence[float], q: float) -> float | None:
        """Percentil com interpolação linear (q entre 0 e 1)."""
        if not xs:
            return None
        xs = sorted(xs)
        k = (len(xs) - 1) * q
        lo, hi = math.floor(k), math.ceil(k)
        return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)

    @staticmethod
    def kappa(matrix: list[list[int]]) -> float | None:
        """Kappa de Cohen: concordância além do acaso."""
        n = sum(map(sum, matrix))
        if not n:
            return None
        observed = sum(matrix[i][i] for i in range(len(matrix))) / n
        expected = sum(sum(matrix[i]) * sum(row[i] for row in matrix) for i in range(len(matrix))) / n**2
        return None if expected == 1 else (observed - expected) / (1 - expected)

    @classmethod
    def bootstrap(cls, values: list, statistic: Callable[[list], float | None], samples: int, seed: int = 42) -> tuple[float, float]:
        """Intervalo de 95% por reamostragem com reposição."""
        if not values:
            return (0.0, 0.0)
        rnd = random.Random(seed)
        results = []
        for _ in range(samples):
            value = statistic([values[rnd.randrange(len(values))] for _ in values])
            if value is not None:
                results.append(value)
        return (cls.percentile(results, 0.025) or 0.0, cls.percentile(results, 0.975) or 0.0)

    @classmethod
    def catch_f1(cls, pairs: list[tuple[bool, bool]]) -> float | None:
        """F1 de "pegar problema" para pares (esperado parar, obtido parar)."""
        tp = sum(e and o for e, o in pairs)
        fp = sum((not e) and o for e, o in pairs)
        fn = sum(e and not o for e, o in pairs)
        return cls.f1(cls.div(tp, tp + fp), cls.div(tp, tp + fn))


# ============================================================================ relatório
@dataclass
class _Tally:
    """Contagens acumuladas chamado a chamado."""

    matrix: list[list[int]] = field(default_factory=lambda: [[0] * len(CLASSES) for _ in CLASSES])
    hits: list[int] = field(default_factory=list)
    problem: list[tuple[bool, bool]] = field(default_factory=list)  # (deveria parar, parou)
    kinds: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0, 0]))  # tp, fp, fn
    score_pairs: list[ScorePair] = field(default_factory=list)
    mismatches: list[MismatchCase] = field(default_factory=list)
    by_category: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # n, acertos
    by_template: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))
    checklist_ok: int = 0
    amount_expected: float = 0.0
    amount_obtained: float = 0.0
    amount_errors: list[float] = field(default_factory=list)

    def add(self, p: Assessment, g: GroundTruth) -> None:
        expected, obtained = g.recommendation.value, p.recommendation.value
        self.matrix[CLASSES.index(expected)][CLASSES.index(obtained)] += 1
        ok = expected == obtained
        self.hits.append(int(ok))
        self.problem.append((not g.recommendation.proceeds, not p.recommendation.proceeds))
        if p.checklist:
            self.checklist_ok += int(p.checklist.complete == g.checklist_ok and set(p.checklist.missing) == set(g.missing))
        flagged, wanted, optional = {f.kind for f in p.findings}, set(g.findings), set(g.optional)
        for kind in flagged | wanted:
            if kind in flagged and kind in wanted:
                self.kinds[kind][0] += 1
            elif kind in flagged and kind not in optional:
                self.kinds[kind][1] += 1
            elif kind in wanted:
                self.kinds[kind][2] += 1
        if g.score is not None and p.score is not None:
            self.score_pairs.append(ScorePair(ticket_id=p.ticket_id, expected=g.score, obtained=p.score))
        for segments, key in ((self.by_category, p.category.value), (self.by_template, g.service_template or "demo")):
            segments[key][0] += 1
            segments[key][1] += int(ok)
        if g.amount_at_issue is not None:
            self.amount_expected += g.amount_at_issue
            self.amount_obtained += p.amount_at_issue
            self.amount_errors.append(abs(g.amount_at_issue - p.amount_at_issue))
        if not ok:
            self.mismatches.append(
                MismatchCase(
                    ticket_id=p.ticket_id,
                    category=p.category.label,
                    expected=expected,
                    obtained=obtained,
                    expected_score=g.score,
                    obtained_score=p.score,
                    missed=sorted(wanted - flagged),
                    extra=sorted((flagged - wanted) - optional),
                )
            )


class ValidationReporter:
    """Gera o relatório de validação de uma rodada (pareceres × gabarito) e aplica o portão de qualidade."""

    def __init__(self, cfg: Settings, ground_truth_dir: Path | None = None):
        self.cfg = cfg
        self.ground_truth_dir = ground_truth_dir or cfg.ground_truth_dir

    def build(self, assessments: list[Assessment]) -> ValidationReport:
        """Relatório completo da rodada: métricas, recortes, operação e portão de qualidade."""
        tally, pairs, missing = _Tally(), [], 0
        for p in assessments:
            g = load_ground_truth(self.ground_truth_dir, p.ticket_id)
            if g is None:
                missing += 1
                continue
            pairs.append((p, g))
            tally.add(p, g)
        n = len(pairs)
        samples = self.cfg.validation.bootstrap_samples

        accuracy = sum(tally.hits) / n if n else 0.0
        accuracy_ci = Stats.bootstrap(tally.hits, lambda xs: sum(xs) / len(xs), samples)
        recalls = [row[i] / sum(row) for i, row in enumerate(tally.matrix) if sum(row)]
        catch = self._problem_catch(tally.problem)
        catch_ci = Stats.bootstrap(tally.problem, Stats.catch_f1, samples) if tally.problem else None
        findings = self._finding_metrics(tally.kinds)
        tp, fp, fn = (sum(v[i] for v in tally.kinds.values()) for i in range(3))
        micro = Stats.binary(tp, fp, fn, 0)
        macro = [m.f1 for m in findings if m.f1 is not None and m.support]
        errors = [x.obtained - x.expected for x in tally.score_pairs]
        mae = statistics.fmean(abs(x) for x in errors) if errors else None
        kappa = Stats.kappa(tally.matrix)
        gate = self._gate(accuracy, kappa, micro.f1, mae)
        return ValidationReport(
            n=n,
            no_ground_truth=missing,
            matrix=tally.matrix,
            accuracy=Interval(value=accuracy, ci_low=accuracy_ci[0], ci_high=accuracy_ci[1]),
            balanced_accuracy=statistics.fmean(recalls) if recalls else 0.0,
            kappa=kappa,
            problem_catch=catch,
            problem_catch_f1_ci=Interval(value=catch.f1 or 0.0, ci_low=catch_ci[0], ci_high=catch_ci[1]) if catch_ci else None,
            checklist_accuracy=tally.checklist_ok / n if n else 0.0,
            findings=findings,
            findings_micro=micro,
            finding_macro_f1=statistics.fmean(macro) if macro else None,
            score_pairs=tally.score_pairs,
            score_mae=mae,
            score_rmse=math.sqrt(statistics.fmean(x * x for x in errors)) if errors else None,
            score_bias=statistics.fmean(errors) if errors else None,
            score_pearson=self._pearson(tally.score_pairs),
            expected_amount_at_issue=round(tally.amount_expected, 2),
            obtained_amount_at_issue=round(tally.amount_obtained, 2),
            amount_at_issue_mae=statistics.fmean(tally.amount_errors) if tally.amount_errors else None,
            by_category=self._segments(tally.by_category),
            by_service_template=self._segments(tally.by_template),
            operations=self._operations([p for p, _ in pairs]),
            mismatches=tally.mismatches,
            gate=gate,
            gate_passed=all(g.passed for g in gate),
        )

    @staticmethod
    def _problem_catch(problem: list[tuple[bool, bool]]) -> BinaryMetric:
        tp = sum(e and o for e, o in problem)
        fp = sum((not e) and o for e, o in problem)
        fn = sum(e and not o for e, o in problem)
        tn = sum((not e) and (not o) for e, o in problem)
        return Stats.binary(tp, fp, fn, tn)

    @staticmethod
    def _finding_metrics(kinds: dict[str, list[int]]) -> list[FindingMetric]:
        out = []
        for kind, (tp, fp, fn) in sorted(kinds.items(), key=lambda x: -(x[1][0] + x[1][2])):
            p, r = Stats.div(tp, tp + fp), Stats.div(tp, tp + fn)
            out.append(FindingMetric(kind=kind, support=tp + fn, tp=tp, fp=fp, fn=fn, precision=p, recall=r, f1=Stats.f1(p, r)))
        return out

    @staticmethod
    def _pearson(pairs: list[ScorePair]) -> float | None:
        xs, ys = [x.expected for x in pairs], [x.obtained for x in pairs]
        if len(pairs) > 2 and len(set(xs)) > 1 and len(set(ys)) > 1:
            return statistics.correlation(xs, ys)
        return None

    @staticmethod
    def _segments(counts: dict[str, list[int]]) -> list[Segment]:
        return sorted((Segment(name=k, n=n, hits=h, accuracy=h / n) for k, (n, h) in counts.items()), key=lambda s: s.accuracy)

    @staticmethod
    def _operations(assessments: list[Assessment]) -> Operations:
        latency = [p.duration_s for p in assessments]
        costs = [p.cost_brl for p in assessments]
        tokens = [(sum(c.input_tokens for c in p.llm_calls), sum(c.output_tokens for c in p.llm_calls)) for p in assessments]
        return Operations(
            latency_p50_s=Stats.percentile(latency, 0.5),
            latency_p95_s=Stats.percentile(latency, 0.95),
            avg_cost_brl=statistics.fmean(costs) if costs else 0.0,
            p95_cost_brl=Stats.percentile(costs, 0.95) or 0.0,
            total_cost_brl=sum(costs),
            avg_input_tokens=statistics.fmean(t[0] for t in tokens) if tokens else 0.0,
            avg_output_tokens=statistics.fmean(t[1] for t in tokens) if tokens else 0.0,
        )

    def _gate(self, accuracy: float, kappa: float | None, finding_f1: float | None, mae: float | None) -> list[GateItem]:
        v = self.cfg.validation
        return [
            GateItem(metric="Acurácia da recomendação", value=accuracy, limit=v.accuracy_min, direction=">=", passed=accuracy >= v.accuracy_min),
            GateItem(metric="Kappa de Cohen", value=kappa, limit=v.kappa_min, direction=">=", passed=(kappa or 0) >= v.kappa_min),
            GateItem(
                metric="F1 dos apontamentos (micro)",
                value=finding_f1,
                limit=v.finding_f1_min,
                direction=">=",
                passed=(finding_f1 or 0) >= v.finding_f1_min,
            ),
            GateItem(
                metric="Erro médio do score", value=mae, limit=v.score_error_max, direction="<=", passed=mae is None or mae <= v.score_error_max
            ),
        ]


# ============================================================================ conjuntos
class DatasetCatalog:
    """Conjuntos de chamados disponíveis (demonstração, validação, enviados pelo painel) e amostragem reprodutível."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg

    def counts(self) -> Counter:
        """Quantidade de chamados por conjunto."""
        return Counter(load_ticket(p).data.dataset for p in list_tickets(self.cfg.tickets_dir))

    def ids(self, dataset: str) -> list[str]:
        """Ids dos chamados de um conjunto ("all" para todos)."""
        folders = list_tickets(self.cfg.tickets_dir)
        return [p.name for p in folders if dataset == "all" or load_ticket(p).data.dataset == dataset]

    @staticmethod
    def sample(ids: list[str], n: int | None, seed: int = 7) -> list[str]:
        """Amostra reprodutível (mesma semente, mesma amostra), em ordem de id."""
        if not n or n >= len(ids):
            return ids
        return sorted(random.Random(seed).sample(ids, n))
