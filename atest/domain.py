"""Modelos de domínio do Atest.AI (Pydantic v2).

Entrada: chamado (extração do Salesforce) + orçamento em Excel + anexos.
Saída: parecer com checklist, notas, score, recomendação e apontamentos.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator


class DomainModel(BaseModel):
    """Base: rejeita campos desconhecidos e aceita enums por valor."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False, populate_by_name=True)


# ============================================================================ enums
class Workstream(StrEnum):
    """Esteira do chamado: SETA (manutenção predial) ou SISR (segurança)."""

    SETA = "SETA"
    SISR = "SISR"


class MaintenanceType(StrEnum):
    """Manutenção corretiva ou preventiva."""

    CORRECTIVE = "corrective"
    PREVENTIVE = "preventive"


class Moment(StrEnum):
    """Momento do chamado: aprovação do orçamento ou retorno após a execução."""

    QUOTE = "quote"  # aprovação do orçamento
    EXECUTION = "execution"  # retorno após a execução do serviço


class Category(StrEnum):
    """Especialidade do chamado (define o checklist e a LPU usada)."""

    PAINTING = "painting"
    WATERPROOFING = "waterproofing"
    ELECTRICAL = "electrical"
    LIGHTING = "lighting"
    AIR_CONDITIONING = "air_conditioning"
    PLUMBING = "plumbing"
    METALWORK = "metalwork"
    CCTV = "cctv"
    ALARM = "alarm"
    CCTV_AND_ALARM = "cctv_and_alarm"

    @property
    def label(self) -> str:
        return CATEGORY_LABEL[self]


CATEGORY_LABEL = {
    Category.PAINTING: "Pintura",
    Category.WATERPROOFING: "Impermeabilização",
    Category.ELECTRICAL: "Elétrica",
    Category.LIGHTING: "Iluminação",
    Category.AIR_CONDITIONING: "Ar-condicionado",
    Category.PLUMBING: "Hidráulica",
    Category.METALWORK: "Serralheria e portas",
    Category.CCTV: "CFTV",
    Category.ALARM: "Alarme",
    Category.CCTV_AND_ALARM: "CFTV e alarme",
}


class Symptom(StrEnum):
    """Sintoma macro: a queixa em uma expressão, antes de qualquer diagnóstico."""

    FINISH_WEAR = "finish_wear"
    MOISTURE_INFILTRATION = "moisture_infiltration"
    LEAK = "leak"
    ELECTRICAL_FAILURE = "electrical_failure"
    POOR_LIGHTING = "poor_lighting"
    MECHANICAL_FAILURE = "mechanical_failure"
    DEGRADED_IMAGE = "degraded_image"
    NO_IMAGE = "no_image"
    FALSE_ALARM = "false_alarm"
    DEVICE_INOPERATIVE = "device_inoperative"
    PREVENTIVE_MAINTENANCE = "preventive_maintenance"

    @property
    def label(self) -> str:
        return SYMPTOM_LABEL[self]


SYMPTOM_LABEL = {
    Symptom.FINISH_WEAR: "Desgaste de pintura ou acabamento",
    Symptom.MOISTURE_INFILTRATION: "Infiltração ou umidade",
    Symptom.LEAK: "Vazamento",
    Symptom.ELECTRICAL_FAILURE: "Falha elétrica",
    Symptom.POOR_LIGHTING: "Iluminação deficiente",
    Symptom.MECHANICAL_FAILURE: "Falha mecânica",
    Symptom.DEGRADED_IMAGE: "Imagem com defeito",
    Symptom.NO_IMAGE: "Sem imagem",
    Symptom.FALSE_ALARM: "Disparo falso",
    Symptom.DEVICE_INOPERATIVE: "Dispositivo não aciona",
    Symptom.PREVENTIVE_MAINTENANCE: "Manutenção preventiva",
}


class AttachmentCategory(StrEnum):
    """Tipo de anexo reconhecido no checklist."""

    QUOTE_DOC = "quote_doc"
    COMPLETION_CERTIFICATE_DOC = "completion_certificate_doc"
    TECHNICAL_REPORT_DOC = "technical_report_doc"
    ROOM_BEFORE_PHOTO = "room_before_photo"
    ROOM_AFTER_PHOTO = "room_after_photo"
    EQUIPMENT_PHOTO = "equipment_photo"
    LABEL_PHOTO = "label_photo"
    REMOVED_ITEMS_PHOTO = "removed_items_photo"
    CCTV_SCREEN_PHOTO = "cctv_screen_photo"
    ALARM_PANEL_PHOTO = "alarm_panel_photo"
    OTHER = "other"


class PhotoMoment(StrEnum):
    """Quando a foto foi tirada em relação ao serviço."""

    BEFORE = "before"
    AFTER = "after"
    DURING = "during"
    UNDETERMINED = "undetermined"


class ItemClassification(StrEnum):
    """Relação de um item do orçamento com o escopo pedido."""

    COMPLIANT = "compliant"
    OUT_OF_SCOPE = "out_of_scope"
    TO_JUSTIFY = "to_justify"


class Match(StrEnum):
    """Se a foto corresponde ao escopo."""

    YES = "yes"
    NO = "no"
    PARTIAL = "partial"
    UNDETERMINED = "undetermined"


class ValidationResult(StrEnum):
    """As três validações que compõem o score (pesos 20/40/40)."""

    SCOPE = "scope"
    QUOTE = "quote"
    PHOTOS = "photos"


class Severity(StrEnum):
    """Severidade de um apontamento (define o desconto na nota)."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Recommendation(StrEnum):
    """Recomendação final do parecer."""

    APPROVE = "approve"
    APPROVE_WITH_CAVEATS = "approve_with_caveats"
    RETURN_TO_SUPPLIER = "return_to_supplier"
    RETURN_LOCKED = "return_locked"
    DETAILED_REVIEW = "detailed_review"
    CHECKLIST_RETURNED = "checklist_returned"

    @property
    def label(self) -> str:
        return {
            "approve": "Aprovar",
            "approve_with_caveats": "Aprovar com ressalvas",
            "return_to_supplier": "Devolver ao fornecedor",
            "return_locked": "Devolver (trava de integridade)",
            "detailed_review": "Análise detalhada",
            "checklist_returned": "Devolvido: checklist incompleto",
        }[self.value]

    @property
    def proceeds(self) -> bool:
        """True se a recomendação deixa o chamado seguir (aprovar ou aprovar com ressalvas)."""
        return self in (Recommendation.APPROVE, Recommendation.APPROVE_WITH_CAVEATS)


class Confidence(StrEnum):
    """Confiança do parecer, reduzida por evidências ilegíveis ou incoerentes."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Stage(StrEnum):
    """Etapas do pipeline, na ordem (usadas no progresso do painel)."""

    CHECKLIST = "checklist"
    SCOPE = "scope"
    QUOTE = "quote"
    PHOTOS = "photos"
    SCORE = "score"
    ASSESSMENT = "assessment"
    DONE = "done"


# ============================================================================ chamado (entrada)
class Branch(DomainModel):
    """Agência onde o serviço é feito."""

    code: str
    name: str
    environment: str = ""


class Supplier(DomainModel):
    """Fornecedor que executa o serviço."""

    name: str
    cnpj: str


class Dates(DomainModel):
    """Datas do chamado."""

    opening: date
    supplier_submission: date
    manager_review: date | None = None


class AttachmentMeta(DomainModel):
    """Metadados de um anexo no ticket.json."""

    file_name: str
    content_type: str
    size_bytes: int = Field(ge=0)
    sent_by: str = "supplier"
    data_upload: date


class ManagerReview(DomainModel):
    """Triagem da empresa gerenciadora antes do backoffice."""

    first_check: str = "forwarded"
    note: str = ""


class Ticket(DomainModel):
    """Chamado de manutenção (ticket.json): categoria, sintoma, escopo em linguagem natural e anexos."""

    ticket_id: str = Field(pattern=r"^\d{8}$")
    workstream: Workstream
    maintenance_type: MaintenanceType
    moment: Moment = Moment.EXECUTION
    category: Category
    symptom: Symptom
    requested_scope: str = Field(min_length=3, description="Escopo descrito por quem abriu o chamado, em linguagem natural")
    branch: Branch
    supplier: Supplier
    quoted_value: float | None = Field(default=None, ge=0)
    dates: Dates
    status: str = "forwarded_to_backoffice"
    origin: str = Field("dataset", description="dataset | upload (enviado pelo painel)")
    dataset: str = Field("demo", description="demonstracao | validacao | enviados")
    manager: ManagerReview = Field(default_factory=ManagerReview)
    attachments: list[AttachmentMeta] = Field(default_factory=list)

    @field_validator("requested_scope")
    @classmethod
    def _non_empty_scope(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("escopo vazio")
        return v.strip()

    def summary_text(self) -> str:
        """Resumo do chamado em português, usado no início de todos os prompts."""
        moment = "aprovação do orçamento" if self.moment == Moment.QUOTE else "retorno após a execução do serviço"
        return (
            f"Chamado {self.ticket_id} | Esteira {self.workstream.value} ({self.maintenance_type.value})\n"
            f"Categoria: {self.category.label} | Sintoma: {self.symptom.label}\n"
            f"Momento da validação: {moment}\n"
            f"Agência: {self.branch.name} (cód. {self.branch.code}) | Ambiente: {self.branch.environment}\n"
            f"Fornecedor: {self.supplier.name}\n"
            f"Abertura: {self.dates.opening:%d/%m/%Y} | Envio do fornecedor: {self.dates.supplier_submission:%d/%m/%Y}\n"
            f"ESCOPO SOLICITADO: {self.requested_scope}"
        )


class Attachment(DomainModel):
    """Anexo físico, numerado como o modelo o vê ("Anexo 3")."""

    index: int = Field(ge=1)
    path: Path
    content_type: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def name(self) -> str:
        return self.path.name

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    @property
    def is_spreadsheet(self) -> bool:
        return "spreadsheet" in self.content_type or self.path.suffix.lower() in (".xlsx", ".xlsm")


# ============================================================================ orçamento (Excel)
class QuoteItem(DomainModel):
    """Linha da tabela de itens do orçamento."""

    n: int = Field(ge=1)
    description: str = Field(min_length=1)
    unit: str
    quantity: float = Field(gt=0)
    unit_value: float = Field(ge=0)
    total_value: float = Field(ge=0)

    @model_validator(mode="after")
    def _total_matches(self) -> QuoteItem:
        if abs(self.quantity * self.unit_value - self.total_value) > 0.51:
            raise ValueError(f"item {self.n}: quantidade × valor unitário ≠ valor total")
        return self


class Quote(DomainModel):
    """Orçamento lido da planilha padrão (abas 'Chamado' e 'Itens', ambas como Tabela do Excel)."""

    file: str
    ticket_id: str
    number: str
    supplier: str
    issued_on: date | None = None
    category: Category
    symptom: Symptom
    scope: str
    items: list[QuoteItem] = Field(min_length=1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_value(self) -> float:
        return round(sum(i.total_value for i in self.items), 2)


# ============================================================================ referências
class LpuItem(DomainModel):
    """Item da tabela de referência de preços (LPU) da esteira."""

    code: str
    description: str
    unit: str
    reference_price: float = Field(gt=0)


class AmountAtIssue(StrEnum):
    """Como um tipo de apontamento entra no valor em questão."""

    ITEM = "item"  # o item inteiro está em questão
    EXCESS = "excess"  # só o que passa da referência ou da quantidade esperada
    NONE = "none"


class FindingType(DomainModel):
    """Definição de um tipo de apontamento na régua (validação, severidade, fase, trava)."""

    validation: ValidationResult
    severity: Severity
    description: str
    phase: int = Field(1, ge=1, le=2)
    reduces_confidence: bool = False
    lock: bool = False
    amount_at_issue: AmountAtIssue = AmountAtIssue.NONE


class Band(DomainModel):
    """Faixa de score e a recomendação correspondente."""

    score_min: int
    recommendation: Recommendation


class ConfidenceRule(DomainModel):
    """Quantos redutores levam a confiança média ou baixa."""

    medium_with_n_reducers: int = 1
    low_with_n_reducers: int = 2


class Rubric(DomainModel):
    """Régua do score (config/rubric.toml)."""

    version: str
    weights: dict[ValidationResult, int]
    discount_by_severity: dict[Severity, int]
    counts: str = "once_per_type_and_validation"
    bands: list[Band]
    confidence: ConfidenceRule
    price_tolerance_pct: float = 10
    hash_max_distance: int = 14
    hash_max_distance_low_detail: int = 6
    hash_crops: list[float] = [0.02, 0.05, 0.1]
    hash_min_detail: float = 9.0
    hash_method: str = ""
    spreadsheet_value_tolerance: float = 1.0
    photo_date_tolerance_days: int = 1
    finding_types: dict[str, FindingType]


# ============================================================================ resultado
class Finding(DomainModel):
    """Apontamento: divergência encontrada, com evidência e desconto."""

    kind: str
    validation: ValidationResult
    severity: Severity
    discount: int
    description: str
    evidence: str
    reference: str = ""
    lock: bool = False
    reduces_confidence: bool = False
    phase: int = 1
    amount_at_issue: float = 0.0


class EvaluatedRequirement(DomainModel):
    """Item do checklist conferido contra os anexos."""

    id: str
    description: str
    met: bool
    attachments: list[str]


class ChecklistResult(DomainModel):
    """Resultado do checklist mínimo."""

    category: Category
    maintenance: MaintenanceType
    moment: Moment
    complete: bool
    uploaded: int
    total: int
    requirements: list[EvaluatedRequirement]
    missing: list[str]


class ClassifiedAttachment(DomainModel):
    """Anexo identificado (categoria, momento, legibilidade)."""

    index: int
    name: str
    category: AttachmentCategory
    moment: PhotoMoment
    readable: bool
    short_description: str


class EvaluatedItem(QuoteItem):
    """Item do orçamento depois da conferência (classificação, referência, apontamentos, valor em questão)."""

    classification: ItemClassification
    reason: str
    lpu_code: str
    reference_price: float | None = None
    expected_quantity_max: float | None = None
    amount_at_issue: float = 0.0
    findings: list[Finding] = Field(default_factory=list)


class EvaluatedPhoto(DomainModel):
    """Foto depois da análise do modelo e da verificação de integridade."""

    file: str
    environment: str
    what_it_shows: str
    moment: PhotoMoment
    readable: bool
    matches_scope: Match
    reason: str
    covered_items: list[int]
    exif_date: datetime | None = None
    reused_from: str | None = None
    integrity_signals: list[str] = Field(default_factory=list)


class Grades(DomainModel):
    """Nota de 0 a 100 de cada validação."""

    scope: int
    quote: int
    photos: int


class LlmCall(DomainModel):
    """Rastro de uma chamada ao modelo, exibido no painel e gravado no banco."""

    task: str
    provider: str = "anthropic"
    model: str
    resolved_model: str = Field("", description="Snapshot que o provedor informou ter usado")
    prompt_version: str = ""
    prompt_hash: str = Field("", description="sha256 do prompt de sistema (12 primeiros dígitos)")
    schema_hash: str = Field("", description="sha256 do schema de saída (12 primeiros dígitos)")
    start: datetime
    duration_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    from_cache: bool = False
    simulated: bool = False
    via_batch: bool = False
    batch_id: str | None = None
    response: dict[str, Any]


class Assessment(DomainModel):
    """Parecer completo de um chamado, com rastreabilidade (versões, modelos, chamadas, custo e tempo)."""

    ticket_id: str
    workstream: Workstream
    category: Category
    symptom: Symptom
    maintenance_type: MaintenanceType
    moment: Moment
    branch: Branch
    supplier: str
    quoted_value: float | None
    requested_scope: str
    generated_at: datetime
    rubric_version: str
    prompts_version: str
    config_signature: str = Field("", description="Impressão digital de régua + prompts + modelos + fase")
    phase: int
    mode: str
    batch_mode: str = "sync"
    models: dict[str, str]
    run_id: str | None = None
    record_id: int | None = Field(None, description="Chave do parecer no banco (usada pelo feedback)")

    checklist: ChecklistResult
    attachments: list[ClassifiedAttachment]
    recommendation: Recommendation
    recommendation_reason: str
    score: int | None = None
    grades: Grades | None = None
    confidence: Confidence | None = None
    confidence_reducers: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    amount_at_issue: float = 0.0
    amount_at_issue_pct: float = 0.0

    scope: dict[str, Any] | None = None
    items: list[EvaluatedItem] = Field(default_factory=list)
    quote_notes: list[str] = Field(default_factory=list)
    photos: list[EvaluatedPhoto] = Field(default_factory=list)
    photo_summary: dict[str, Any] | None = None

    summary: str = ""
    supplier_message: str = ""
    llm_calls: list[LlmCall] = Field(default_factory=list)
    duration_s: float = 0.0
    stage_durations_s: dict[str, float] = Field(default_factory=dict)
    cost_usd: float = 0.0
    cost_brl: float = 0.0
