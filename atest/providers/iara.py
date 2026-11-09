"""Provedor IARA GenAI (plataforma de LLM do Itaú) pelo SDK `iara_genai_sdk` (import `iaragenai`).

A IARA expõe uma API no formato Chat Completions da OpenAI e roteia para um backend (azure_openai, bedrock ou vertex).
Modelos: "iara:gpt-4.1" usa o backend padrão das opções; "iara:bedrock/<modelo>" escolhe o backend por modelo.

Credenciais no ambiente (ou em config/.secrets.toml): IARA_CLIENT_ID, IARA_CLIENT_SECRET e, opcional, IARA_ACCESS_TOKEN.
Opções em [default.llm.provider_options.iara] (settings.toml):
- environment: dev | homol | prod
- provider: backend padrão (azure_openai | bedrock | vertex)
- json_mode: "json_schema" (response_format com schema estrito), "json_object" (JSON livre + schema no prompt)
  ou "prompt" (sem response_format, só o schema no prompt) — use os dois últimos se o backend recusar o primeiro
- pdf_mode: "file" (envia o PDF como arquivo) ou "text" (extrai o texto localmente com pypdf)
- enable_polling: repassado à IARA (aguarda a resposta quando a inferência é enfileirada)
- models: catálogo {backend: [modelos]}; define o backend de cada modelo e as opções do painel
- text_only: modelos do catálogo que não leem imagem (recusados com erro claro em tarefas com anexos)
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import time
import types
import typing
from typing import Any

from pydantic import BaseModel, ValidationError

from ..observability import event
from .base import DocumentPart, ImagePart, Provider, ProviderError, ProviderResponse, Request, T, TextPart, Usage

BACKENDS = ("azure_openai", "bedrock", "vertex")
JSON_MODES = ("json_schema", "json_object", "prompt")
PDF_MODES = ("file", "text")
_TRANSIENT_NAMES = ("RateLimit", "Timeout", "Connection", "ServiceUnavailable", "InternalServer", "Overloaded", "Throttl")


# --------------------------------------------------------------------------- utilitários
def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Lê um campo de objeto ou dict (a forma exata da resposta do SDK IARA pode variar)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def split_backend(model: str, default: str, catalog: dict[str, str] | None = None) -> tuple[str, str]:
    """Backend e id do modelo: 'bedrock/modelo' → ('bedrock', 'modelo'); senão o backend do catálogo; senão o padrão."""
    if "/" in model:
        prefix, rest = model.split("/", 1)
        if prefix.strip().lower() in BACKENDS:
            return prefix.strip().lower(), rest.strip()
    return (catalog or {}).get(model, default), model


def catalog_backends(models: dict[str, list[str]] | None) -> dict[str, str]:
    """{backend: [modelos]} (config [llm.provider_options.iara.models]) → {modelo: backend}."""
    out: dict[str, str] = {}
    for backend, ids in (models or {}).items():
        if backend not in BACKENDS:
            raise ValueError(f"iara.models: backend desconhecido {backend!r} (use {', '.join(BACKENDS)})")
        for mid in ids:
            out.setdefault(mid, backend)
    return out


def strict_schema(output: type) -> dict:
    """JSON Schema do modelo Pydantic no formato estrito do response_format (todo objeto fechado e com tudo obrigatório)."""

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(v) for v in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k == "default":
                continue
            # "properties" e "$defs" são mapas nome → schema (não são schemas): percorre só os valores
            out[k] = {name: walk(s) for name, s in v.items()} if k in ("properties", "$defs") and isinstance(v, dict) else walk(v)
        if isinstance(out.get("properties"), dict) or (out.get("type") == "object" and "additionalProperties" not in out):
            out["additionalProperties"] = False
            out["required"] = list(out.get("properties", {}))
        return out

    return walk(output.model_json_schema())


def strip_fences(text: str) -> str:
    """Remove cercas ```json ... ``` que alguns modelos colocam em volta do JSON."""
    text = text.strip()
    if m := re.fullmatch(r"```[a-zA-Z]*\s*(.*?)\s*```", text, flags=re.DOTALL):
        return m.group(1)
    return text


# erros do Pydantic de "esperava lista/objeto e veio outra coisa": candidatos a JSON que veio como string
_CONTAINER_ERRORS = {"list_type", "dict_type", "model_type", "model_attributes_type", "tuple_type", "set_type"}


def _loads(value: str) -> Any:
    """JSON dentro de uma string (com ou sem cercas de código); devolve None se não for JSON de lista/objeto."""
    text = strip_fences(value)
    if text[:1] not in ("{", "["):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def parse_output(data: Any, output: type[T], max_rounds: int = 20) -> tuple[T, list[str]]:
    """Valida a resposta no schema, corrigindo o JSON "duplamente codificado" que alguns modelos devolvem pela IARA.

    Claude via Bedrock (e outros) às vezes devolve um campo lista/objeto como string com JSON dentro, e às vezes essa
    string é o objeto inteiro de novo: {"attachments": "{\\"attachments\\": [...]}"}. Também acontece a resposta toda vir
    como string ou embrulhada numa chave só ({"AttachmentIdentification": {...}}). A correção só age onde o schema espera
    lista/objeto e recebeu texto; o resultado continua validado pelo Pydantic. Devolve o objeto e as correções aplicadas.

    Backends que não aplicam o schema à risca (json_object, prompt, alguns modelos via Bedrock) às vezes omitem um campo
    obrigatório. Campo de lista ou texto que faltou entra vazio ([] / ""), e campo que aceita nulo entra como null;
    faltar booleano, número ou objeto continua sendo erro, porque inventar esses valores mudaria a análise.
    """
    repairs: list[str] = []
    for _ in range(max_rounds):
        if isinstance(data, str) and (inner := _loads(data)) is not None:
            data = inner
            repairs.append("resposta inteira como string")
            continue
        try:
            return output.model_validate(data), repairs
        except ValidationError as e:
            if _repair(data, e, repairs):
                continue
            # objeto embrulhado numa chave que não é campo do schema: {"NomeDoSchema": {...}}
            if isinstance(data, dict) and len(data) == 1:
                ((key, inner),) = data.items()
                inner = _loads(inner) if isinstance(inner, str) else inner
                if key not in output.model_fields and isinstance(inner, dict):
                    data = inner
                    repairs.append(f"objeto embrulhado em '{key}'")
                    continue
            if _fill_missing(data, e, output, repairs):  # último recurso: resposta parcial no formato certo
                continue
            raise
    return output.model_validate(data), repairs


def _repair(data: Any, error: ValidationError, repairs: list[str]) -> bool:
    """Decodifica, no lugar, os campos que vieram como string com JSON onde o schema pede lista/objeto."""
    fixed = False
    for err in error.errors():
        loc = err["loc"]
        if err["type"] not in _CONTAINER_ERRORS or not isinstance(err.get("input"), str) or not loc:
            continue
        value = _loads(err["input"])
        if value is None:
            continue
        parent = data
        try:
            for step in loc[:-1]:
                parent = parent[step]
        except (KeyError, IndexError, TypeError):
            continue
        key = loc[-1]
        if not isinstance(parent, dict | list) or (isinstance(parent, dict) and key not in parent):
            continue
        if isinstance(parent, dict) and isinstance(value, dict) and key in value:
            # a string era o objeto pai inteiro de novo: traz o campo e os irmãos que vieram dentro dela
            parent.update(value)
            repairs.append(f"'{'.'.join(map(str, loc))}' trazia o objeto inteiro como string")
        else:
            parent[key] = value
            repairs.append(f"'{'.'.join(map(str, loc))}' veio como string com JSON")
        fixed = True
    return fixed


def _empty_value(annotation: Any) -> tuple[bool, Any]:
    """Valor neutro para um campo omitido: lista → [], texto → "", opcional → None. (False, None) se não houver."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (typing.Union, types.UnionType) and type(None) in args:
        return True, None
    if annotation is str:
        return True, ""
    if annotation in (list, set, tuple) or origin in (list, set, tuple):
        return True, []
    return False, None


def _field_annotation(model: type[BaseModel], loc: tuple) -> Any:
    """Anotação do campo no caminho de um erro de validação, descendo por submodelos e listas de submodelos."""
    current: Any = model
    for step in loc:
        if isinstance(step, int):  # índice de lista: o tipo é o do elemento
            args = typing.get_args(current)
            current = args[0] if args else Any
            continue
        if not (isinstance(current, type) and issubclass(current, BaseModel)) or step not in current.model_fields:
            return None
        current = current.model_fields[step].annotation
    return current


def _fill_missing(data: Any, error: ValidationError, output: type[BaseModel], repairs: list[str]) -> bool:
    """Preenche, no lugar, os campos obrigatórios omitidos que têm valor neutro (ver parse_output)."""
    fixed = False
    for err in error.errors():
        loc = err["loc"]
        if err["type"] != "missing" or not loc or isinstance(loc[-1], int):
            continue
        ok, value = _empty_value(_field_annotation(output, loc))
        if not ok:
            continue
        parent = data
        try:
            for step in loc[:-1]:
                parent = parent[step]
        except (KeyError, IndexError, TypeError):
            continue
        model = _field_annotation(output, loc[:-1]) if loc[:-1] else output
        fields = set(model.model_fields) if isinstance(model, type) and issubclass(model, BaseModel) else set()
        # só completa uma resposta parcial do formato certo: tem algum campo esperado e nenhum desconhecido
        partial = isinstance(parent, dict) and bool(set(parent) & fields) and set(parent) <= fields
        if partial and loc[-1] not in parent:
            parent[loc[-1]] = value
            repairs.append(f"'{'.'.join(map(str, loc))}' omitido; preenchido com {json.dumps(value)}")
            fixed = True
    return fixed


def pdf_text(data: bytes) -> str:
    """Texto do PDF (pdf_mode = "text"). Requer `pip install pypdf`."""
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - depende do ambiente
        raise ProviderError("pdf_mode = 'text' requer o pacote pypdf (pip install pypdf)") from e
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def schema_instructions(output: type) -> str:
    """Instrução de formato anexada ao prompt de sistema quando o backend não recebe o schema por parâmetro."""
    schema = json.dumps(output.model_json_schema(), ensure_ascii=False)
    return (
        "\n\nResponda SOMENTE com um objeto JSON válido (sem texto antes ou depois, sem cercas de código) "
        f"que siga exatamente este JSON Schema:\n{schema}"
    )


def convert(req: Request, output: type, json_mode: str = "json_schema", pdf_mode: str = "file") -> list[dict]:
    """Converte as partes neutras em mensagens Chat Completions (texto, imagem e PDF)."""
    content: list[dict] = []
    for p in req.parts:
        if isinstance(p, TextPart):
            content.append({"type": "text", "text": p.text})
        elif isinstance(p, ImagePart):
            content.append({"type": "image_url", "image_url": {"url": f"data:{p.mime};base64,{p.b64}"}})
        elif isinstance(p, DocumentPart):
            title = p.title or "document.pdf"
            if pdf_mode == "text":
                content.append({"type": "text", "text": f"[PDF: {title}]\n{pdf_text(p.data) or '(PDF sem texto extraível)'}"})
            else:
                content.append({"type": "file", "file": {"filename": title, "file_data": f"data:{p.mime};base64,{p.b64}"}})
    system = req.system if json_mode == "json_schema" else req.system + schema_instructions(output)
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def is_transient(exc: Exception) -> bool:
    """Erro que vale repetir: limite de taxa, 5xx, timeout ou conexão (por status ou nome da classe do SDK)."""
    for attr in ("status_code", "status", "http_status"):
        status = getattr(exc, attr, None)
        if status is None:
            status = getattr(getattr(exc, "response", None), attr, None)
        if isinstance(status, int):
            return status == 429 or status >= 500 or status == 408
    name = type(exc).__name__
    return any(t in name for t in _TRANSIENT_NAMES) or isinstance(exc, TimeoutError | ConnectionError)


# --------------------------------------------------------------------------- provedor
class IaraProvider(Provider):
    """LLMs pela IARA GenAI (Chat Completions), com saída estruturada validada pelo Pydantic."""

    name = "iara"
    supports_batch = False  # a Batch API da IARA ainda não está integrada; o modo lote cai para chamadas síncronas

    def __init__(
        self,
        timeout_s: float = 180,
        max_retries: int = 4,
        client: Any = None,
        environment: str = "dev",
        provider: str = "azure_openai",
        json_mode: str = "json_schema",
        pdf_mode: str = "file",
        enable_polling: bool = True,
        models: dict[str, list[str]] | None = None,
        text_only: list[str] | None = None,
    ):
        if json_mode not in JSON_MODES:
            raise ValueError(f"iara.json_mode inválido: {json_mode!r} (use {', '.join(JSON_MODES)})")
        if pdf_mode not in PDF_MODES:
            raise ValueError(f"iara.pdf_mode inválido: {pdf_mode!r} (use {', '.join(PDF_MODES)})")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.environment = environment
        self.backend = provider
        self.json_mode = json_mode
        self.pdf_mode = pdf_mode
        self.enable_polling = enable_polling
        self.catalog = catalog_backends(models)  # modelo → backend (azure_openai, bedrock, vertex)
        self.text_only = set(text_only or ())  # modelos que não leem imagem
        self._injected = client
        self._clients: dict[str, Any] = {}

    # ------------------------------------------------------------------ clientes (um por backend)
    def client(self, backend: str) -> Any:
        """Cliente do SDK para o backend (injetado nos testes ou criado na primeira chamada)."""
        if self._injected is not None:
            return self._injected
        if backend not in self._clients:
            try:
                from iaragenai import IaraGenAI
            except ImportError as e:
                raise ProviderError("provedor 'iara' requer o pacote iara_genai_sdk (pip install iara_genai_sdk, Artifactory do Itaú)") from e
            kwargs: dict[str, Any] = {
                "client_id": os.getenv("IARA_CLIENT_ID"),
                "client_secret": os.getenv("IARA_CLIENT_SECRET"),
                "environment": self.environment,
                "provider": backend,
            }
            if token := os.getenv("IARA_ACCESS_TOKEN"):
                kwargs["access_token"] = token
            self._clients[backend] = IaraGenAI(**kwargs)
        return self._clients[backend]

    # ------------------------------------------------------------------ chamada
    def _kwargs(self, req: Request, model: str, output: type) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": convert(req, output, self.json_mode, self.pdf_mode),
            "max_tokens": req.max_tokens,
        }
        if self.json_mode == "json_schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": output.__name__, "schema": strict_schema(output), "strict": True},
            }
        elif self.json_mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        if req.effort in ("low", "medium", "high"):
            kwargs["reasoning_effort"] = req.effort
        if self.enable_polling:
            kwargs["enable_polling"] = True
        return kwargs

    def _create(self, client: Any, kwargs: dict[str, Any], task: str) -> Any:
        """Chama a IARA repetindo erros transitórios com espera exponencial; esgotado, sinaliza contingência."""
        attempt = 0
        while True:
            try:
                return client.chat.completions.create(**kwargs)
            except ProviderError:
                raise
            except Exception as e:
                if not is_transient(e):
                    raise ProviderError(f"[{task}] {type(e).__name__}: {e}") from e
                if attempt >= self.max_retries:
                    raise ProviderError(f"[{task}] {type(e).__name__}: {e}", transient=True) from e
                time.sleep(min(30.0, 2**attempt) * (0.5 + random.random() / 2))
                attempt += 1

    def generate(self, req: Request, output: type[T]) -> ProviderResponse[T]:
        backend, model = split_backend(req.model, self.backend, self.catalog)
        if model in self.text_only and any(isinstance(p, ImagePart) or (isinstance(p, DocumentPart) and self.pdf_mode == "file") for p in req.parts):
            raise ProviderError(
                f"[{req.task}] o modelo {model} não lê imagens nem PDFs e esta tarefa envia anexos; "
                "escolha um modelo com visão (ex.: gpt-4.1, claude-sonnet-5, gemini-2.5-flash) ou use-o só em tarefas de texto"
            )
        resp = self._create(self.client(backend), self._kwargs(req, model, output), req.task)
        choices = _get(resp, "choices") or []
        if not choices:
            raise ProviderError(f"[{req.task}] resposta da IARA sem choices")
        choice = choices[0]
        message = _get(choice, "message")
        if _get(choice, "finish_reason") == "length":
            raise ProviderError(f"[{req.task}] resposta cortada por max_tokens ({req.max_tokens})")
        if refusal := _get(message, "refusal"):
            raise ProviderError(f"[{req.task}] recusa do modelo: {refusal}")
        text = _get(message, "content") or ""
        if isinstance(text, list):  # alguns backends devolvem a lista de blocos de conteúdo
            text = "".join(_get(b, "text", "") or "" for b in text)
        if not text.strip():
            raise ProviderError(f"[{req.task}] resposta da IARA vazia")
        try:
            data = json.loads(strip_fences(text))
        except ValueError as e:
            raise ProviderError(f"[{req.task}] resposta da IARA não é JSON: {text[:300]!r}") from e
        try:
            obj, repairs = parse_output(data, output)
        except ValidationError as e:
            raise ProviderError(f"[{req.task}] resposta fora do schema {output.__name__}: {e}") from e
        if repairs:
            # comportamento esperado de alguns backends (ex.: Claude via Bedrock) e já corrigido: fica só no log JSON,
            # sem aviso no console (que mostra WARNING ou acima)
            event("iara_json_repaired", task=req.task, model=model, backend=backend, repairs=repairs)
        u = _get(resp, "usage")
        cache = _get(_get(u, "prompt_tokens_details"), "cached_tokens", 0) or 0
        prompt = _get(u, "prompt_tokens", 0) or 0
        # prompt_tokens inclui os tokens lidos do cache; separamos para o cálculo de custo (mesma convenção dos outros provedores)
        return ProviderResponse(
            obj=obj,
            usage=Usage(input=max(0, prompt - cache), output=_get(u, "completion_tokens", 0) or 0, cache_read_tokens=cache),
            resolved_model=_get(resp, "model") or model,
            response_id=_get(resp, "id") or "",
        )
