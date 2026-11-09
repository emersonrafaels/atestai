"""Formatos de saída do modelo (saída estruturada).

Cada classe vira o JSON Schema enviado em `output_config.format` via `client.messages.parse(output_format=...)`.
As descrições dos campos fazem parte das instruções: o modelo as lê junto com o schema.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .domain import AttachmentCategory, ItemClassification, Match, PhotoMoment


class LlmOutput(BaseModel):
    """Base das saídas estruturadas pedidas ao modelo (sem campos extras)."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- etapa 0: checklist
class IdentifiedAttachment(LlmOutput):
    """Identificação de um anexo pelo modelo rápido."""

    index: int = Field(description="Número do anexo, como no rótulo 'Anexo N'")
    category: AttachmentCategory = Field(description="Uma única categoria, a mais específica")
    moment: PhotoMoment = Field(description="before = problema/estado anterior; after = resultado/peça nova; during = durante o serviço")
    readable: bool = Field(description="false se escura, tremida, sem foco ou cortada a ponto de não identificar o conteúdo")
    short_description: str = Field(description="Até 12 palavras, em português, dizendo o que aparece")


class AttachmentIdentification(LlmOutput):
    """Saída da tarefa identify_attachments."""

    attachments: list[IdentifiedAttachment]


# --------------------------------------------------------------------------- validação 1: escopo
class Quantity(LlmOutput):
    """Quantidade citada no escopo."""

    description: str
    quantity: float
    unit: str


class ScopeReading(LlmOutput):
    """Saída da tarefa scope: o pedido traduzido em critérios de aceite."""

    local: str = Field(description="Local do serviço (agência, área)")
    environment: str = Field(description="Ambiente ou equipamento-alvo, como escrito no chamado")
    equipment: str = Field(description="Equipamento citado, ou vazio")
    requested_services: list[str] = Field(description="Ações pedidas, ex.: 'repintar paredes', 'limpar e ajustar foco da câmera 04'")
    mentioned_quantities: list[Quantity] = Field(description="Só quantidades explícitas no texto")
    acceptance_criteria: list[str] = Field(description="Frases verificáveis para conferir orçamento e fotos")
    expected_evidence: list[str] = Field(description="Que fotos/documentos comprovariam o RESULTADO pedido")
    before_evidence_applicable: bool = Field(
        description="true se o serviço altera o estado físico (reparo, troca, pintura, limpeza); false para testes/inspeções"
    )
    consistent_with_category_symptom: bool = Field(description="O texto do escopo é coerente com a categoria e o sintoma informados?")
    coherence_note: str = Field(description="Se incoerente, explique em uma frase; senão vazio")
    vague_scope: bool = Field(
        description="true se o texto não permite saber o que fazer, onde ou em quê, a ponto de impedir a conferência do orçamento"
    )
    vague_reason: str = Field(description="Se vago, por quê; senão vazio")


# --------------------------------------------------------------------------- validação 2: orçamento × escopo
class ItemReview(LlmOutput):
    """Conferência de um item do orçamento contra o escopo."""

    n: int
    classification: ItemClassification
    reason: str = Field(description="Uma frase objetiva que a pessoa analista possa usar como justificativa")
    expected_quantity_max: float = Field(description="Maior quantidade plausível segundo o escopo; -1 se não dá para estimar")
    plausible_quantity: bool
    duplicate_of: int = Field(description="n de um item ANTERIOR que cobra a mesma coisa; 0 se não há")
    lpu_code: str = Field(description="Código equivalente na tabela de referência, ou NO_REFERENCE")


class QuoteReview(LlmOutput):
    """Saída da tarefa quote_review."""

    items: list[ItemReview]
    notes: str


# --------------------------------------------------------------------------- validação 3: fotos
class AnalyzedPhoto(LlmOutput):
    """Leitura de uma foto pelo modelo de visão."""

    index: int
    environment: str = Field(description="Onde a foto foi tirada, ex.: 'backoffice', 'fachada externa', 'imagem de câmera de corredor'")
    what_it_shows: str
    moment: PhotoMoment
    readable: bool = Field(description="Uma foto nítida de uma tela que mostra imagem desfocada É legível")
    matches_scope: Match
    reason: str
    covered_items: list[int] = Field(description="Itens do orçamento que a foto evidencia")


class PhotoAnalysis(LlmOutput):
    """Saída da tarefa photos: foto a foto e a visão de conjunto."""

    photos: list[AnalyzedPhoto]
    has_before_photo: bool
    has_done_service_photo: bool = Field(description="Alguma foto legível comprova o RESULTADO pedido, no local do escopo")
    done_justification: str
    items_without_photo: list[int]
    notes: str


# --------------------------------------------------------------------------- parecer
class AssessmentText(LlmOutput):
    """Saída da tarefa assessment: resumo e mensagem ao fornecedor."""

    summary: str = Field(description="2 a 3 frases; comece pela recomendação e pelo motivo principal")
    supplier_message: str = Field(description="Ações ao fornecedor, uma por apontamento; vazio se aprovar sem apontamentos ou análise detalhada")
