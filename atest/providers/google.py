"""Provedor Google Gemini: `google-genai` com `response_schema=<Pydantic>`. Requer `pip install google-genai` e GEMINI_API_KEY."""

from __future__ import annotations

from typing import Any

from .base import DocumentPart, ImagePart, Provider, ProviderError, ProviderResponse, Request, T, TextPart, Usage


def convert(req: Request) -> list[Any]:
    """Converte as partes neutras para o formato de conteúdo do google-genai."""
    from google.genai import types

    parts = []
    for p in req.parts:
        if isinstance(p, TextPart):
            parts.append(types.Part.from_text(text=p.text))
        elif isinstance(p, ImagePart | DocumentPart):
            parts.append(types.Part.from_bytes(data=p.data, mime_type=p.mime))
    return [types.Content(role="user", parts=parts)]


class GoogleProvider(Provider):
    """Gemini pelo SDK google-genai, com response_schema a partir do modelo Pydantic."""

    name = "google"

    def __init__(self, timeout_s: float = 180, max_retries: int = 4, client: Any = None):
        from google import genai

        self.client = client or genai.Client(http_options={"timeout": int(timeout_s * 1000)})

    def generate(self, req: Request, output: type[T]) -> ProviderResponse[T]:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=req.system, response_mime_type="application/json", response_schema=output, max_output_tokens=req.max_tokens
        )
        try:
            resp = self.client.models.generate_content(model=req.model, contents=convert(req), config=config)
        except errors.ServerError as e:
            raise ProviderError(f"[{req.task}] {e}", transient=True) from e
        finish = str(getattr((resp.candidates or [None])[0], "finish_reason", "") or "")
        if finish.endswith("MAX_TOKENS"):
            raise ProviderError(f"[{req.task}] resposta cortada em max_output_tokens={req.max_tokens}", truncated=True)
        obj = resp.parsed if isinstance(resp.parsed, output) else (output.model_validate_json(resp.text) if resp.text else None)
        if obj is None:
            raise ProviderError(f"[{req.task}] resposta sem JSON válido")
        u = resp.usage_metadata
        cache = (u.cached_content_token_count or 0) if u else 0
        input = ((u.prompt_token_count or 0) - cache) if u else 0
        output_tokens = ((u.candidates_token_count or 0) + (u.thoughts_token_count or 0)) if u else 0
        return ProviderResponse(
            obj=obj,
            usage=Usage(input=input, output=output_tokens, cache_read_tokens=cache),
            resolved_model=resp.model_version or req.model,
            response_id=resp.response_id or "",
        )
