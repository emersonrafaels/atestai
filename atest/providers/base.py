"""Contrato neutro entre o Atest.AI e qualquer provedor de LLM (Anthropic, OpenAI, Google Gemini...).

As etapas do pipeline montam a requisição com `Texto`, `Imagem` e `Documento`; cada provedor traduz para o formato
do seu SDK, pede saída estruturada no schema Pydantic e devolve `ProviderResponse` com uso de tokens normalizado.
Trocar de provedor é mudar a string do modelo no TOML: "anthropic:claude-sonnet-5-5", "openai:<modelo>", "google:<modelo>".
"""

from __future__ import annotations

import base64
import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


# --------------------------------------------------------------------------- conteúdo neutro
@dataclass(frozen=True)
class TextPart:
    """Trecho de texto da requisição."""

    text: str


@dataclass(frozen=True)
class ImagePart:
    """Imagem (bytes) da requisição."""

    data: bytes
    mime: str = "image/jpeg"

    @property
    def b64(self) -> str:
        """Conteúdo em base64."""
        return base64.standard_b64encode(self.data).decode()


@dataclass(frozen=True)
class DocumentPart:
    """Documento PDF (bytes) da requisição."""

    data: bytes
    mime: str = "application/pdf"
    title: str = ""

    @property
    def b64(self) -> str:
        """Conteúdo em base64."""
        return base64.standard_b64encode(self.data).decode()


Part = TextPart | ImagePart | DocumentPart


def signature_parts(parts: list[Part]) -> str:
    """Representação estável das partes, para a chave de cache."""
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, TextPart):
            h.update(b"T" + p.text.encode())
        else:
            h.update(b"B" + p.mime.encode() + hashlib.sha256(p.data).digest())
    return h.hexdigest()


@dataclass
class Request:
    """Requisição neutra (sem SDK): tarefa, prompt de sistema, partes, modelo e limites."""

    task: str
    system: str
    parts: list[Part]
    model: str  # id do modelo no provedor (sem o prefixo "provedor:")
    max_tokens: int
    effort: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def key(self, output: type[BaseModel], provider: str) -> str:
        """Identifica a requisição para cache e auditoria: provedor, modelo, prompt, conteúdo e schema."""
        base = json.dumps(
            [provider, self.model, self.system, self.max_tokens, self.effort, output.model_json_schema()], sort_keys=True, ensure_ascii=False
        )
        return hashlib.sha256((base + signature_parts(self.parts)).encode()).hexdigest()


@dataclass
class Usage:
    """Tokens consumidos por uma chamada."""

    input: int = 0
    output: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class ProviderResponse(Generic[T]):
    """Resposta de um provedor: objeto validado, uso e o id efetivo do modelo."""

    obj: T
    usage: Usage
    resolved_model: str  # o id que o provedor diz ter usado (snapshot), para auditoria
    response_id: str = ""
    via_batch: bool = False
    batch_id: str | None = None


class ProviderError(RuntimeError):
    """Erro do provedor; `transitorio=True` indica que vale tentar o modelo de contingência."""

    def __init__(self, msg: str, transient: bool = False):
        super().__init__(msg)
        self.transient = transient


# --------------------------------------------------------------------------- contrato
class Provider(ABC):
    """Interface de um provedor de LLM. Lote assíncrono é opcional (`supports_batch`)."""

    name: str
    supports_batch: bool = False

    @abstractmethod
    def generate(self, req: Request, output: type[T]) -> ProviderResponse[T]:
        """Uma chamada síncrona com saída estruturada validada pelo Pydantic."""

    # API de lote (opcional): só provedores com batch nativo implementam
    def create_batch(self, items: list[tuple[str, Request, type[BaseModel]]]) -> str:
        """Envia várias requisições como um lote assíncrono; devolve o id do lote."""
        raise NotImplementedError(f"{self.name} não implementa lote")

    def batch_finished(self, batch_id: str) -> bool:
        """True quando o lote terminou de processar."""
        raise NotImplementedError

    def batch_results(self, batch_id: str, outputs: dict[str, type[BaseModel]]) -> dict[str, ProviderResponse | Exception]:
        """Respostas do lote por chave da requisição (ou o erro de cada uma)."""
        raise NotImplementedError
