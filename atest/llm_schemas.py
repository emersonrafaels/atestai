"""Formatos de saída do modelo (saída estruturada).

Cada classe vira o JSON Schema enviado em `output_config.format` via `client.messages.parse(output_format=...)`.
As descrições dos campos fazem parte das instruções: o modelo as lê junto com o schema.
"""

from __future__ import annotations

from typing import Literal

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
    uncovered_services: list[str] = Field(
        description=(
            "Serviços pedidos no escopo (ou na descrição da solução) que não têm nenhum item no orçamento, um por linha, em "
            "português simples. Não liste o que já está dentro de outro item (ex.: mão de obra embutida no item do serviço)."
        )
    )
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


class QuantityCheck(LlmOutput):
    """Contagem, somando as fotos, do que um item físico do orçamento cobra (peças, área, unidades)."""

    item: int = Field(description="Número do item do orçamento")
    what_was_counted: str = Field(description="O que foi contado, ex.: 'peças de piso quebradas', 'luminárias apagadas'")
    per_photo: str = Field(description="Quanto aparece em cada foto, ex.: 'Anexo 2: 1; Anexo 3: 2'; mesmo ponto em duas fotos conta uma vez")
    count_seen: float = Field(description="Total visto somando as fotos, na unidade contada (ex.: 7 peças)")
    estimated_quantity: float = Field(
        description="Quantidade estimada NA UNIDADE DO ITEM (ex.: 7 peças de 45x45 cm = 1,42 m²); -1 se não dá para estimar"
    )
    reasoning: str = Field(description="Como chegou à estimativa (tamanho da peça assumido, margem de corte), em uma frase")


class PhotoAnalysis(LlmOutput):
    """Saída da tarefa photos: foto a foto e a visão de conjunto."""

    photos: list[AnalyzedPhoto]
    has_before_photo: bool
    done_justification: str = Field(
        description="Antes de decidir done_service: que foto mostra o resultado pedido e o que confirma (ou contradiz) o local"
    )
    done_service: Match = Field(
        description=(
            "yes = foto legível mostra o RESULTADO pedido no local do escopo; partial = mostra o resultado, mas nada na imagem "
            "permite confirmar o local (e nada o contradiz); no = nenhuma foto mostra o resultado, ou a foto contradiz o local; "
            "undetermined = fotos ilegíveis"
        )
    )
    items_without_photo: list[int]
    quantity_checks: list[QuantityCheck] = Field(
        description=(
            "Para cada item físico cobrado por quantidade ou área do que aparece danificado nas fotos (piso, revestimento, peças, "
            "luminárias): some o que as fotos mostram e estime a quantidade na unidade do item. Itens que dependem da mesma área "
            "(ex.: demolição, piso novo e rejunte) recebem um check cada. Não inclua deslocamento, visita ou mão de obra genérica."
        )
    )
    notes: str


# --------------------------------------------------------------------------- documentos (OCR)
class ReadPrice(LlmOutput):
    """Preço que aparece num documento."""

    description: str = Field(description="Produto ou serviço como escrito no documento")
    value: float = Field(description="Preço unitário em reais, como número (ex.: 303.25)")
    quote_item: int = Field(description="Número do item do orçamento a que este preço se refere; 0 se não corresponde a nenhum")
    same_product: Match = Field(
        description=(
            "yes = mesmo produto do item (especificação e medidas batem); partial = parece o mesmo, mas o orçamento não traz "
            "especificação ou medidas para confirmar; no = outro produto ou outra especificação"
        )
    )


class ReadDocument(LlmOutput):
    """Leitura (OCR) de um documento anexado e conferência com o chamado."""

    index: int
    kind: Literal["service_report", "completion_certificate", "technical_report", "price_reference", "invoice", "other"] = Field(
        description=(
            "service_report = relatório/ordem de atendimento do técnico; completion_certificate = termo de conclusão; "
            "technical_report = laudo ou relatório técnico; price_reference = anúncio, print de loja ou cotação de preço; "
            "invoice = nota fiscal ou recibo"
        )
    )
    handwritten: bool = Field(description="true se o conteúdo principal foi preenchido à mão")
    legible: Match = Field(description="yes = dá para ler tudo; partial = partes ilegíveis; no = não dá para ler o conteúdo")
    transcription: str = Field(description="Transcrição fiel do texto, na ordem de leitura; trechos que não dá para ler como [ilegível]")
    issuer: str = Field(description="Empresa, loja ou pessoa que emitiu o documento; vazio se não aparece")
    service_date: str = Field(description="Data do atendimento ou do documento em dd/mm/aaaa; vazio se não aparece")
    start_time: str = Field(description="Hora de início (hh:mm); vazio se não aparece")
    end_time: str = Field(description="Hora de término (hh:mm); vazio se não aparece")
    branch: str = Field(description="Agência citada (código e/ou nome); vazio se não aparece")
    problem: str = Field(description="Problema descrito no documento; vazio se não há")
    solution: str = Field(description="Solução ou serviço descrito no documento; vazio se não há")
    has_signature: bool = Field(description="true se há assinatura ou carimbo")
    service_status: Match = Field(
        description=(
            "O documento PROVA que o serviço já foi feito? yes só com afirmação explícita: verbo no passado ('foi instalada', "
            "'trocamos', 'executado'), 'serviço concluído' marcado ou termo de conclusão/aceite assinado. no = descreve proposta, "
            "diagnóstico ou o que será feito. undetermined = só substantivo ('instalação de…', 'troca de…') ou não dá para saber"
        )
    )
    prices: list[ReadPrice] = Field(description="Preços que aparecem no documento (anúncio, cotação, nota)")
    matches_ticket: Match = Field(
        description=(
            "yes = o documento é deste chamado (agência, serviço) e confirma o que foi pedido/feito; no = algo ESCRITO contradiz o "
            "chamado (outra agência, outro serviço, outro equipamento); partial = é do contexto, mas não confirma o ponto pedido; "
            "undetermined = ilegível"
        )
    )
    divergences: list[str] = Field(description="Cada diferença concreta entre o documento e o chamado ou o orçamento; vazio se não há")
    reason: str = Field(description="Uma frase justificando matches_ticket")


class DocumentAnalysis(LlmOutput):
    """Saída da tarefa documents."""

    documents: list[ReadDocument]
    notes: str


# --------------------------------------------------------------------------- parecer
class AssessmentText(LlmOutput):
    """Saída da tarefa assessment: resumo e mensagem ao fornecedor."""

    summary: str = Field(description="2 a 3 frases; comece pela recomendação e pelo motivo principal")
    supplier_message: str = Field(description="Ações ao fornecedor, uma por apontamento; vazio se aprovar sem apontamentos ou análise detalhada")
