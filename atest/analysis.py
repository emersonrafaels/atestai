"""Contrato das etapas da análise: o contexto compartilhado de um chamado e a classe base de cada etapa.

Cada etapa (checklist, escopo, orçamento, fotos, score, parecer) recebe o mesmo `AnalysisContext`, lê o que as
anteriores produziram e acrescenta o seu resultado. Uma etapa pode encerrar a análise antes do fim (por exemplo,
checklist incompleto) preenchendo `halt`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from .domain import Attachment, ChecklistResult, ClassifiedAttachment, EvaluatedItem, Finding, Stage
from .llm_schemas import AssessmentText, PhotoAnalysis, ScopeReading
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
    photos: list[Attachment] = field(default_factory=list)
    photo_analysis: PhotoAnalysis | None = None
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
        """Resultado consolidado (score + apontamentos + valor em questão), usado na redação do parecer."""
        assert self.score is not None
        return {
            **self.score.model_dump(mode="json"),
            "findings": [f.model_dump(mode="json") for f in self.findings],
            "amount_at_issue": self.amount_at_issue,
            "amount_at_issue_pct": self.amount_at_issue_pct,
        }


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
