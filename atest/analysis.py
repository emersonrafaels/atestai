"""Contrato das etapas da análise: o contexto compartilhado de um chamado e a classe base de cada etapa.

Cada etapa (checklist, escopo, orçamento, fotos, score, parecer) recebe o mesmo `AnalysisContext`, lê o que as
anteriores produziram e acrescenta o seu resultado. Uma etapa pode encerrar a análise antes do fim (por exemplo,
checklist incompleto) preenchendo `halt`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from .domain import Attachment, ChecklistResult, ClassifiedAttachment, EvaluatedDocument, EvaluatedItem, Finding, Stage
from .formatting import brl
from .llm_schemas import AssessmentText, PhotoAnalysis, ScopeReading, ServiceCoverage
from .score import ScoreCalculator, ScoreResult

if TYPE_CHECKING:
    from .config import Settings
    from .llm import LlmSession
    from .repository import LoadedTicket, References


@dataclass
class AnalysisContext:
    """Estado de um chamado ao longo do pipeline."""

    ticket: LoadedTicket
    session: LlmSession
    run_id: str | None = None
    durations: dict[str, float] = field(default_factory=dict)
    attachments: list[ClassifiedAttachment] = field(default_factory=list)
    checklist: ChecklistResult | None = None
    scope: ScopeReading | None = None
    findings: list[Finding] = field(default_factory=list)
    confidence_reducers: list[str] = field(default_factory=list)  # motivos extras de baixa confiança (ex.: orçamento ilegível)
    items: list[EvaluatedItem] = field(default_factory=list)
    quote_notes: list[str] = field(default_factory=list)
    service_coverage: list[ServiceCoverage] = field(default_factory=list)
    photos: list[Attachment] = field(default_factory=list)
    photo_analysis: PhotoAnalysis | None = None
    documents: list[EvaluatedDocument] = field(default_factory=list)
    integrity: dict[str, dict] = field(default_factory=dict)
    score: ScoreResult | None = None
    amount_at_issue: float = 0.0
    amount_at_issue_pct: float = 0.0
    text: AssessmentText | None = None
    halt: dict[str, Any] | None = None  # campos do parecer final quando uma etapa encerra a análise

    @property
    def halted(self) -> bool:
        return self.halt is not None

    def scoring_input(self) -> dict[str, Any]:
        """Resultado consolidado (score + apontamentos + valor em questão + observações das etapas), para a redação do parecer."""
        assert self.score is not None
        return {
            **self.score.model_dump(mode="json"),
            "findings": [f.model_dump(mode="json") for f in self.findings],
            "amount_at_issue": self.amount_at_issue,
            "amount_at_issue_pct": self.amount_at_issue_pct,
            "observations": self.observations(),
            "rationale": self.rationale(),
            "moment": self.ticket.data.moment.value,
        }

    def rationale(self) -> list[str]:
        """Racional técnico do engenheiro, montado por regra a partir das etapas: cobertura do pedido, contagem nas fotos,
        preço e leitura do problema. Vai sempre para a redação do parecer, com ou sem apontamento."""
        out: list[str] = []
        mark = {"yes": "coberto", "partial": "coberto só em parte", "no": "SEM item no orçamento", "undetermined": "não conferido"}
        for c in self.service_coverage:
            items = ", ".join(str(i) for i in c.items)
            out.append(f"Serviço pedido “{c.service}”: {mark.get(c.covered.value, c.covered.value)}"
                       + (f" (itens {items})" if items else "") + (f". {c.note}" if c.note else ""))
        by_n = {i.n: i for i in self.items}
        for q in self.photo_analysis.quantity_checks if self.photo_analysis else []:
            item = by_n.get(q.item)
            if item is None:
                continue
            seen = (f"cerca de {q.estimated_quantity:g} {item.unit}" if q.estimated_quantity > 0 else "não dá para estimar")
            out.append(f"Contagem nas fotos, item {item.n} ({item.description}): cobrado {item.quantity:g} {item.unit}; as fotos "
                       f"somam {q.count_seen:g} ({q.what_was_counted}), {seen}. {q.reasoning}".strip())
        priced = [i for i in self.items if i.reference_price]
        for i in priced:
            pct = 100 * (i.unit_value / i.reference_price - 1)
            out.append(f"Preço do item {i.n}: {brl(i.unit_value)} × referência {brl(i.reference_price)} ({pct:+.0f}%)")
        if self.items and not priced:
            out.append("Nenhum item tem equivalente na tabela de referência: o preço não pôde ser comparado com a tabela")
        for d in self.documents:
            for p in d.prices:
                if (item := by_n.get(p.quote_item)) and p.value > 0:
                    out.append(f"Preço de mercado no documento {d.file}: {p.description} a {brl(p.value)} × item {item.n} a {brl(item.unit_value)}")
        if self.photo_analysis and self.photo_analysis.problem_assessment.strip():
            out.append(f"O que as fotos mostram do problema: {self.photo_analysis.problem_assessment.strip()}")
        return out

    def observations(self, limit: int = 600) -> list[str]:
        """Observações das etapas que não viram apontamento (orçamento, fotos, documentos), resumidas para o parecer."""

        def cut(text: str) -> str:
            text = " ".join(text.split())
            return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

        out = [f"Orçamento: {cut(n)}" for n in self.quote_notes if n.strip()]
        if self.photo_analysis is not None and self.photo_analysis.notes.strip():
            out.append(f"Fotos: {cut(self.photo_analysis.notes)}")
        for d in self.documents:
            if d.divergences:
                out.append(f"Documento {d.file}: {cut('; '.join(d.divergences))}")
        return out


class AnalysisStage(ABC):
    """Uma etapa do pipeline. Subclasses definem `name`, `progress` e `run`."""

    name: ClassVar[str]
    progress: ClassVar[Stage]

    def __init__(self, cfg: Settings, references: References, scorer: ScoreCalculator):
        self.cfg = cfg
        self.references = references
        self.scorer = scorer

    @property
    def rubric(self):
        return self.references.rubric

    @abstractmethod
    def run(self, ctx: AnalysisContext) -> None:
        """Executa a etapa, lendo e completando o contexto."""
