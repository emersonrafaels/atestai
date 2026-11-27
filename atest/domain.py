"""Modelos de domínio do Atest.AI (Pydantic v2).

Entrada: chamado (extração do Salesforce) + orçamento em Excel + anexos.
Saída: parecer com checklist, notas, score, recomendação e apontamentos.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetCoreSchemaHandler,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_core import core_schema


class DomainModel(BaseModel):
    """Base: rejeita campos desconhecidos e aceita enums por valor."""

    model_config = ConfigDict(
        extra="forbid", use_enum_values=False, populate_by_name=True
    )


# ============================================================================ rótulos em português (valores internos → tela)
VALIDATION_PT = {
    "scope": "Escopo",
    "quote": "Orçamento",
    "photos": "Evidências fotográficas",
}
SEVERITY_PT = {"critical": "crítica", "high": "alta", "medium": "média", "low": "baixa"}
CONFIDENCE_PT = {"high": "alta", "medium": "média", "low": "baixa"}
MAINTENANCE_PT = {"corrective": "corretiva", "preventive": "preventiva"}
MOMENT_PT = {"quote": "aprovação de orçamento", "execution": "atestação do serviço"}


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


# O que cada etapa do chamado espera de evidência: vai no resumo do chamado, que abre todos os prompts.
STAGE_EXPECTATIONS = {
    "quote": (
        "Momento da validação: APROVAÇÃO DO ORÇAMENTO. O serviço AINDA NÃO FOI FEITO. Nesta etapa se espera o orçamento "
        "e fotos do problema (o antes) que mostrem o local, o dano e a extensão que justificam os itens e as quantidades. "
        "Não se espera nem se cobra foto do depois, do serviço concluído, da peça instalada ou termo de conclusão: a falta "
        "deles é normal nesta etapa."
    ),
    "execution": (
        "Momento da validação: RETORNO APÓS A EXECUÇÃO (atestação do serviço). As fotos precisam comprovar o RESULTADO "
        "pedido no local do escopo; foto do antes e documentos de conclusão conforme o checklist."
    ),
}


def stage_expectations(moment: str) -> str:
    """Texto do que se espera de evidência na etapa do chamado (aprovação do orçamento ou atestação)."""
    return STAGE_EXPECTATIONS.get(str(moment), STAGE_EXPECTATIONS["execution"])


# ============================================================================ cadastro (categorias, sintomas e locais)
class CatalogEntry(DomainModel):
    """Item do cadastro: código gravado no chamado, nome na tela e onde vale."""

    value: str = Field(min_length=1, max_length=60)
    label: str = Field(min_length=1, max_length=80)
    enabled: bool = Field(
        True,
        description="desativado: some das listas de escolha, mas chamados antigos seguem com o nome",
    )
    workstreams: list[Workstream] = Field(
        default_factory=list,
        description="categoria ou local: esteiras em que vale (vazio = SETA e SISR)",
    )
    categories: list[str] = Field(
        default_factory=list,
        description="sintoma: categorias em que vale (vazio = todas)",
    )


CatalogKind = str  # "categories" | "symptoms" | "locations"


class Catalog(DomainModel):
    """Cadastro editável de categorias, sintomas e locais (config/catalog.toml + portal de configuração)."""

    categories: list[CatalogEntry]
    symptoms: list[CatalogEntry]
    locations: list[CatalogEntry] = Field(default_factory=list)

    def entries(self, kind: CatalogKind) -> list[CatalogEntry]:
        return getattr(self, kind)

    def codes(self, kind: CatalogKind, enabled_only: bool = False) -> list[str]:
        return [e.value for e in self.entries(kind) if e.enabled or not enabled_only]

    def label(self, kind: CatalogKind, value: str) -> str:
        """Nome do código; código desconhecido (ex.: apagado do cadastro) aparece como veio."""
        for e in self.entries(kind):
            if e.value == value:
                return e.label
        return value.replace("_", " ") if kind != "locations" else value


_CATALOG: Catalog | None = None


def use_catalog(catalog: Catalog) -> None:
    """Define o cadastro em uso (o dos TOML com as alterações do portal por cima)."""
    global _CATALOG
    _CATALOG = catalog


def current_catalog() -> Catalog:
    """Cadastro em uso; sem um definido, o dos arquivos de configuração."""
    global _CATALOG
    if _CATALOG is None:
        from .config import load_settings  # import tardio: config depende deste módulo

        _CATALOG = load_settings().catalog
    return _CATALOG


class CatalogCode(str):
    """Código de um item do cadastro (str), com `.value` e `.label` como os enums de antes.

    A validação só confere o formato: chamados e pareceres antigos continuam legíveis mesmo que o código saia do
    cadastro; a pertença ao cadastro é conferida na entrada (envio pelo painel, portal).
    """

    kind: ClassVar[str] = ""

    @property
    def value(self) -> str:
        return str(self)

    @property
    def label(self) -> str:
        return current_catalog().label(self.kind, str(self))

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls,
            core_schema.str_schema(min_length=1),
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )


class Category(CatalogCode):
    """Especialidade do chamado (define o checklist); cadastrada em config/catalog.toml ou no portal."""

    kind = "categories"


class Symptom(CatalogCode):
    """Sintoma macro: a queixa em uma expressão, antes de qualquer diagnóstico."""

    kind = "symptoms"


def location_label(value: str) -> str:
    """Nome do local do chamado (branch.environment) no cadastro."""
    return current_catalog().label("locations", value) if value else ""


class AttachmentCategory(StrEnum):
    """Tipo de anexo reconhecido no checklist."""

    QUOTE_DOC = "quote_doc"
    COMPLETION_CERTIFICATE_DOC = "completion_certificate_doc"
    TECHNICAL_REPORT_DOC = "technical_report_doc"
    PRICE_REFERENCE_DOC = "price_reference_doc"
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

    @property
    def label(self) -> str:
        return VALIDATION_PT[self.value]


class Severity(StrEnum):
    """Severidade de um apontamento (define o desconto na nota)."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def label(self) -> str:
        return SEVERITY_PT[self.value]


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

    @property
    def label(self) -> str:
        return CONFIDENCE_PT[self.value]


class Stage(StrEnum):
    """Etapas do pipeline, na ordem (usadas no progresso do painel)."""

    CHECKLIST = "checklist"
    SCOPE = "scope"
    RELATED = "related"  # chamados da mesma agência (possível duplicidade)
    QUOTE = "quote"
    PHOTOS = "photos"
    DOCUMENTS = "documents"
    COHERENCE = (
        "coherence"  # categoria/sintoma e solução × problema, com todas as evidências
    )
    SCORE = "score"
    ASSESSMENT = "assessment"
    DONE = "done"


# ============================================================================ chamado (entrada)
# Palavras que não identificam a agência no nome ("Itaú Ag. Saúde" = "Ag. Saúde" = "Saude"); "fictícia" marca as
# agências inventadas dos dados de demonstração.
_BRANCH_NAME_NOISE = re.compile(r"\b(?:itau|ag|agencia|unibanco|ficticia|ficticio)\b")


def branch_name_key(name: str) -> str:
    """Nome da agência normalizado para comparação: sem acento, caixa, pontuação, "Itaú" nem "Ag."/"Agência"."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    plain = re.sub(r"[^a-z0-9 ]+", " ", plain.casefold())
    return " ".join(_BRANCH_NAME_NOISE.sub(" ", plain).split())


class Branch(DomainModel):
    """Agência onde o serviço é feito: pelo nome, pelo código (0 a 9999) ou pelos dois."""

    code: str = Field(
        "",
        description="Número do ponto (código da agência), de 0 a 9999, gravado com 4 dígitos (ex.: 0418); vazio = não informado",
    )
    name: str = Field("", description="Nome da agência; vazio = não informado")
    environment: str = Field(
        "",
        description="Local do chamado: ambiente da agência (backoffice, fachada, autoatendimento…)",
    )

    @field_validator("code", mode="before")
    @classmethod
    def _normalize_code(cls, v: Any) -> str:
        """Aceita número ou texto ("418", "0418", " 0.418 ") e grava com 4 dígitos; recusa o que não é de 0 a 9999."""
        if v is None:
            return ""
        text = re.sub(r"[\s.]", "", str(v))
        if not text:
            return ""
        if not text.isdigit() or int(text) > 9999:
            raise ValueError(
                f"número do ponto '{v}' inválido: use um número de 0 a 9999"
            )
        return f"{int(text):04d}"

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, v: Any) -> str:
        return " ".join(str(v or "").split())

    @model_validator(mode="after")
    def _name_or_code(self) -> Branch:
        if not self.code and not self.name:
            raise ValueError("informe o nome da agência ou o número do ponto")
        return self

    @property
    def label(self) -> str:
        """Como a agência aparece na tela e nos prompts: "Ag. Saúde (núm. do ponto 0661)", "Ag. Saúde" ou "Agência núm. do ponto 0661"."""
        if self.name and self.code:
            return f"{self.name} (núm. do ponto {self.code})"
        return self.name or f"Agência núm. do ponto {self.code}"

    def same_as(self, other: Branch) -> bool:
        """Mesma agência? Pelo código quando os dois têm; senão, pelo nome normalizado (`branch_name_key`)."""
        if self.code and other.code:
            return self.code == other.code
        mine, theirs = branch_name_key(self.name), branch_name_key(other.name)
        return bool(mine) and mine == theirs


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
    requested_scope: str = Field(
        min_length=3,
        description="Descrição detalhada do problema, escrita por quem abriu o chamado (o escopo)",
    )
    solution_description: str = Field(
        "",
        max_length=4000,
        description="Descrição da solução (opcional): o que será ou foi feito; pode vir já na aprovação do orçamento",
    )
    branch: Branch
    supplier: Supplier
    blocks_opening: bool | None = Field(
        None,
        description="o problema está impedindo a abertura da agência? (None = não informado)",
    )
    quoted_value: float | None = Field(default=None, ge=0)
    dates: Dates
    status: str = "forwarded_to_backoffice"
    origin: str = Field("dataset", description="dataset | upload (enviado pelo painel)")
    dataset: str = Field(
        "scenarios",
        description="scenarios (cenários de teste e casos do deck) | validation | itau | casos | uploaded",
    )
    manager: ManagerReview = Field(default_factory=ManagerReview)
    attachments: list[AttachmentMeta] = Field(default_factory=list)

    @field_validator("requested_scope")
    @classmethod
    def _non_empty_scope(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("escopo vazio")
        return v.strip()

    def summary_text(self) -> str:
        """Resumo do chamado em português, usado no início de todos os prompts (inclui o que se espera na etapa)."""
        return (
            f"Chamado {self.ticket_id} | Esteira {self.workstream.value} ({self.maintenance_type.value})\n"
            f"Categoria: {self.category.label} | Sintoma: {self.symptom.label}\n"
            f"{stage_expectations(self.moment)}\n"
            f"Agência: {self.branch.label}"
            f" | Local do chamado: {location_label(self.branch.environment) or 'não informado'}\n"
            + (
                f"Impede a abertura da agência: {'sim' if self.blocks_opening else 'não'}\n"
                if self.blocks_opening is not None
                else ""
            )
            + f"Fornecedor: {self.supplier.name}\n"
            f"Abertura: {self.dates.opening:%d/%m/%Y} | Envio do fornecedor: {self.dates.supplier_submission:%d/%m/%Y}\n"
            f"ESCOPO SOLICITADO: {self.requested_scope}"
            + (
                f"\nDESCRIÇÃO DA SOLUÇÃO (informada no chamado): {self.solution_description.strip()}"
                if self.solution_description.strip()
                else ""
            )
        )


class Attachment(DomainModel):
    """Anexo físico, numerado como o modelo o vê ("Anexo 3")."""

    index: int = Field(ge=1)
    path: Path
    content_type: str
    # foto extraída de um PDF (relatório da SISR no formato pergunta + Sim/Não + foto): o PDF, a página e o texto ao lado
    source: str = ""
    page: int = 0
    context: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def name(self) -> str:
        return self.path.name

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    @property
    def is_spreadsheet(self) -> bool:
        return "spreadsheet" in self.content_type or self.path.suffix.lower() in (
            ".xlsx",
            ".xlsm",
        )


# ============================================================================ orçamento (Excel)
class QuoteItem(DomainModel):
    """Linha da tabela de itens do orçamento."""

    n: int = Field(ge=1)
    description: str = Field(min_length=1)
    unit: str
    lpu: bool = Field(
        True,
        description="item da tabela de preços (LPU); False = fora da LPU. Planilha sem a coluna: True",
    )
    quantity: float = Field(gt=0)
    unit_value: float = Field(ge=0)
    total_value: float = Field(ge=0)

    @model_validator(mode="after")
    def _total_matches(self) -> QuoteItem:
        if abs(self.quantity * self.unit_value - self.total_value) > 0.51:
            raise ValueError(
                f"item {self.n}: quantidade × valor unitário ≠ valor total"
            )
        return self


class Quote(DomainModel):
    """Orçamento lido da planilha padrão (abas 'Chamado' e 'Itens', ambas como Tabela do Excel)."""

    file: str
    ticket_id: str
    number: str
    supplier: str
    supplier_cnpj: str = ""
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
    """Item da LPU (Lista de Preços Unitários) da esteira."""

    code: str
    description: str
    unit: str
    reference_price: float = Field(gt=0)


class AmountAtIssue(StrEnum):
    """Como um tipo de apontamento entra no valor em questão."""

    ITEM = "item"  # o item inteiro está em questão
    EXCESS = "excess"  # só o que passa da referência ou da quantidade esperada
    NONE = "none"


class Extent(StrEnum):
    """Como medir quanto do que o fornecedor enviou o apontamento atinge (desconto proporcional)."""

    VALUE = "value"  # valor em questão do tipo ÷ total do orçamento
    PHOTOS = "photos"  # fotos apontadas ÷ fotos analisadas
    ITEMS = "items"  # itens apontados ÷ itens a conferir
    SERVICES = "services"  # serviços pedidos sem item (parcial conta metade) ÷ serviços pedidos
    DOCUMENTS = "documents"  # documentos apontados ÷ documentos lidos
    WHOLE = "whole"  # o chamado inteiro (escopo vago, falta a foto do depois…)


class FindingOverride(DomainModel):
    """Ajuste de um tipo de apontamento numa esteira: o que não vier preenchido segue o padrão."""

    enabled: bool | None = None
    severity: Severity | None = None


class FindingType(DomainModel):
    """Definição de um tipo de apontamento na régua (validação, severidade, fase, trava)."""

    validation: ValidationResult
    severity: Severity
    description: str
    phase: int = Field(1, ge=1, le=2)
    reduces_confidence: bool = False
    lock: bool = False
    amount_at_issue: AmountAtIssue = AmountAtIssue.NONE
    extent: Extent = Field(
        Extent.WHOLE,
        description="como medir a fração atingida: o desconto cresce com ela (proporcional ao que foi enviado)",
    )
    returns: bool = Field(
        False,
        description="falta do fornecedor: com este apontamento, a recomendação é no máximo devolver ao fornecedor",
    )
    review: bool = Field(
        False,
        description="pede conferência da pessoa analista (ex.: possível chamado duplicado): leva à análise detalhada",
    )
    caveats: bool = Field(
        False,
        description="ponto a esclarecer que não impede aprovar: com este apontamento, no máximo aprovar com ressalvas",
    )
    enabled: bool = Field(
        True,
        description="desativado: o apontamento não é gerado nem desconta (portal de configuração)",
    )
    absorbs: list[str] = Field(
        default_factory=list,
        description="tipos da mesma validação que deixam de descontar quando este aparece (o mesmo problema visto por outro ângulo)",
    )
    by_workstream: dict[Workstream, FindingOverride] = Field(
        default_factory=dict,
        description="ajustes por esteira (SETA, SISR): ativar/desativar e severidade diferentes do padrão",
    )

    def for_workstream(self, workstream: str) -> FindingType:
        """O tipo com o ajuste da esteira aplicado (sem ajuste, o próprio tipo)."""
        o = next(
            (v for k, v in self.by_workstream.items() if k.value == workstream), None
        )
        if o is None:
            return self
        patch = {k: v for k, v in o.model_dump().items() if v is not None}
        return self.model_copy(update=patch) if patch else self


class Band(DomainModel):
    """Faixa de score e a recomendação correspondente."""

    score_min: int
    recommendation: Recommendation


class ConfidenceRule(DomainModel):
    """Quantos redutores levam a confiança média ou baixa."""

    medium_with_n_reducers: int = 1
    low_with_n_reducers: int = 2


class RelatedTicketsRule(DomainModel):
    """Chamados da mesma agência: quais entram na comparação e a partir de que chance viram apontamento."""

    enabled: bool = True
    window_days: int = Field(
        60,
        ge=0,
        le=90,
        description="compara com os chamados da agência abertos até N dias antes (ou depois) da abertura deste",
    )
    include_still_open: bool = Field(
        True,
        description="compara também com os chamados da agência que seguem abertos, abertos antes da janela",
    )
    closed_statuses: list[str] = Field(
        default_factory=lambda: [
            "approved",
            "rejected",
            "cancelled",
            "closed",
            "completed",
            "paid",
        ],
        description="situações de chamado encerrado; qualquer outra conta como aberto",
    )
    min_probability: int = Field(
        70,
        ge=1,
        le=100,
        description="chance (%) de ser o mesmo problema a partir da qual vira o apontamento possible_duplicate_ticket",
    )
    show_probability: int = Field(
        40,
        ge=0,
        le=100,
        description="a partir desta chance (%), o chamado aparece no parecer como relacionado, sem apontamento",
    )
    max_candidates: int = Field(
        12, ge=1, le=30, description="no máximo N chamados comparados pelo modelo"
    )

    def is_open(self, status: str) -> bool:
        return status.strip().lower() not in {s.lower() for s in self.closed_statuses}


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
    relevant_amount_at_issue_pct: float = Field(
        10,
        ge=0,
        le=100,
        description="a partir deste % do orçamento em questão, a nota de Orçamento fica limitada a 100 − % em questão",
    )
    proportional_floor: float = Field(
        0.5,
        ge=0,
        le=1,
        description="fração da severidade que o apontamento desconta mesmo atingindo pouco do que foi enviado",
    )
    max_amount_at_issue_for_caveats_pct: float = Field(
        30,
        ge=0,
        le=100,
        description="a partir deste % do orçamento em questão, o chamado volta ao fornecedor (0 desliga)",
    )
    max_amount_at_issue_for_approve_pct: float = Field(
        10,
        ge=0,
        le=100,
        description="acima deste % do orçamento em questão, 'Aprovar' vira 'Aprovar com ressalvas' (0 desliga)",
    )
    market_price_tolerance_pct: float = Field(
        25,
        ge=0,
        description="preço até N% acima do valor de mercado anexado não é apontado (margem do fornecedor sobre o varejo)",
    )
    photo_quantity_tolerance_pct: float = Field(
        25,
        ge=0,
        description="quantidade cobrada até N% acima do que as fotos mostram não é apontada (margem de corte e perda)",
    )
    related_tickets: RelatedTicketsRule = Field(
        default_factory=RelatedTicketsRule,
        description="comparação com chamados da mesma agência (possível duplicidade)",
    )
    special_causes: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "causa especial (vandalism, natural_disaster) → códigos de categoria ou sintoma que a indicam no chamado; "
            "abrir com a causa errada vira o apontamento cause_miscategorized"
        ),
    )
    finding_types: dict[str, FindingType]

    def cause_of(self, category: str, symptom: str) -> str:
        """Causa especial indicada pela categoria ou pelo sintoma do chamado ("" = nenhuma)."""
        for cause, codes in self.special_causes.items():
            if category in codes or symptom in codes:
                return cause
        return ""

    def for_workstream(self, workstream: str) -> Rubric:
        """Régua com os ajustes da esteira aplicados a cada tipo de apontamento."""
        return self.model_copy(
            update={
                "finding_types": {
                    k: t.for_workstream(workstream)
                    for k, t in self.finding_types.items()
                }
            }
        )


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
    absorbed_by: str = Field(
        "",
        description="tipo que absorveu este apontamento: segue como evidência, mas não desconta",
    )
    returns: bool = Field(
        False,
        description="falta do fornecedor: leva a devolver ao fornecedor qualquer que seja a nota",
    )
    review: bool = Field(
        False,
        description="pede conferência da pessoa analista: leva à análise detalhada (salvo trava)",
    )
    caveats: bool = Field(
        False,
        description="ponto a esclarecer: com a nota de aprovar, a recomendação vira aprovar com ressalvas",
    )
    extent: float = Field(
        1.0,
        ge=0,
        le=1,
        description="fração do que foi enviado que o tipo atinge (1 = tudo)",
    )
    extent_label: str = Field(
        "",
        description="a fração em palavras, ex.: '2 de 3 serviços pedidos', '25% do orçamento'",
    )


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
    # item Não LPU: o item da LPU que cumpre a mesma função (ex.: parede removível → parede de drywall)
    similar_lpu: LpuItem | None = None
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
    contradicts_report: str = ""
    exif_date: datetime | None = None
    reused_from: str | None = None
    integrity_signals: list[str] = Field(default_factory=list)
    # foto extraída de PDF: o PDF de origem, a página e o texto ao lado (pergunta e resposta)
    source: str = ""
    page: int = 0
    context: str = ""


class ReportAnswer(DomainModel):
    """Pergunta de relatório em formato checklist e a resposta marcada (yes, no, not_applicable, blank, other)."""

    question: str
    answer: str = "other"
    note: str = ""
    has_photo: bool = False


class DocumentPrice(DomainModel):
    """Preço citado num documento (anúncio, cotação, nota), ligado ao item do orçamento quando há."""

    description: str
    value: float
    quote_item: int = 0
    same_product: Match = Match.UNDETERMINED


class EvaluatedDocument(DomainModel):
    """Documento anexado (imagem ou PDF) depois da leitura (OCR) e da conferência contra o chamado."""

    file: str
    kind: str = "other"
    handwritten: bool = False
    legible: Match
    transcription: str = ""
    issuer: str = ""
    service_date: str = ""
    start_time: str = ""
    end_time: str = ""
    branch: str = ""
    problem: str = ""
    solution: str = ""
    has_signature: bool = False
    service_status: Match = Match.UNDETERMINED
    prices: list[DocumentPrice] = Field(default_factory=list)
    answers: list[ReportAnswer] = Field(default_factory=list)
    matches_ticket: Match
    divergences: list[str] = Field(default_factory=list)
    reason: str = ""


class RelatedTicket(DomainModel):
    """Chamado da mesma agência comparado com este, com a chance de ser o mesmo problema (leitura do modelo)."""

    ticket_id: str
    source: str = Field("tickets", description="tickets | history")
    opening: date
    status: str
    is_open: bool
    category: str = ""
    category_label: str = ""
    symptom_label: str = ""
    environment: str = ""
    scope: str = ""
    supplier: str = ""
    quoted_value: float | None = None
    days_apart: int = Field(
        0, description="dias entre as aberturas (positivo = aberto antes deste)"
    )
    in_window: bool = Field(
        True, description="aberto dentro da janela; False = entrou por seguir aberto"
    )
    probability: int = Field(
        0, ge=0, le=100, description="chance de ser o mesmo problema (%)"
    )
    relation: str = Field("different", description="same_problem | related | different")
    reason: str = ""
    matching_points: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    flagged: bool = Field(
        False, description="virou o apontamento possible_duplicate_ticket"
    )


class RelatedTicketsCheck(DomainModel):
    """O que a etapa de chamados da agência comparou e com que parâmetros."""

    window_days: int
    include_still_open: bool
    min_probability: int
    show_probability: int
    candidates_found: int = Field(
        0, description="chamados da agência dentro dos critérios (antes do limite)"
    )
    tickets: list[RelatedTicket] = Field(
        default_factory=list,
        description="os comparados, do mais provável para o menos",
    )
    skipped: str = Field(
        "", description="motivo de a checagem não rodar (vazio = rodou)"
    )


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
    resolved_model: str = Field(
        "", description="Snapshot que o provedor informou ter usado"
    )
    prompt_version: str = ""
    prompt_hash: str = Field(
        "", description="sha256 do prompt de sistema (12 primeiros dígitos)"
    )
    schema_hash: str = Field(
        "", description="sha256 do schema de saída (12 primeiros dígitos)"
    )
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
    config_signature: str = Field(
        "", description="Impressão digital de régua + prompts + modelos + fase"
    )
    phase: int
    mode: str
    batch_mode: str = "sync"
    models: dict[str, str]
    run_id: str | None = None
    record_id: int | None = Field(
        None, description="Chave do parecer no banco (usada pelo feedback)"
    )

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
    service_coverage: list[dict[str, Any]] = Field(
        default_factory=list,
        description="serviços pedidos × itens do orçamento que os executam (racional do engenheiro)",
    )
    photos: list[EvaluatedPhoto] = Field(default_factory=list)
    photo_summary: dict[str, Any] | None = None
    documents: list[EvaluatedDocument] = Field(
        default_factory=list, description="documentos lidos por OCR (imagem ou PDF)"
    )
    related: RelatedTicketsCheck | None = Field(
        None,
        description="chamados da mesma agência comparados (possível duplicidade); None em pareceres antigos",
    )
    coherence: dict[str, Any] | None = Field(
        None,
        description="categoria/sintoma × causa vista nas evidências e solução × problema relatado; None em pareceres antigos",
    )

    summary: str = ""
    supplier_message: str = ""
    llm_calls: list[LlmCall] = Field(default_factory=list)
    duration_s: float = 0.0
    stage_durations_s: dict[str, float] = Field(default_factory=dict)
    cost_usd: float = 0.0
    cost_brl: float = 0.0
