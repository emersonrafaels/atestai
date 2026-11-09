"""Provedor OpenAI: Responses API com `responses.parse(text_format=<Pydantic>)`. Requer `pip install openai` e OPENAI_API_KEY."""

from __future__ import annotations

from typing import Any

from .base import DocumentPart, ImagePart, Provider, ProviderError, ProviderResponse, Request, T, TextPart, Usage


def convert(req: Request) -> list[dict]:
    """Converte as partes neutras para a entrada da Responses API (texto, imagem e arquivo)."""
    content: list[dict] = []
    for p in req.parts:
        if isinstance(p, TextPart):
            content.append({"type": "input_text", "text": p.text})
        elif isinstance(p, ImagePart):
            content.append({"type": "input_image", "image_url": f"data:{p.mime};base64,{p.b64}"})
        elif isinstance(p, DocumentPart):
            content.append({"type": "input_file", "filename": p.title or "document.pdf", "file_data": f"data:{p.mime};base64,{p.b64}"})
    return [{"role": "user", "content": content}]


class OpenAIProvider(Provider):
    """Modelos da OpenAI pela Responses API, com saída estruturada (responses.parse)."""

    name = "openai"

    def __init__(self, timeout_s: float = 180, max_retries: int = 4, client: Any = None):
        import openai

        self._openai = openai
        self.client = client or openai.OpenAI(max_retries=max_retries, timeout=timeout_s)

    def generate(self, req: Request, output: type[T]) -> ProviderResponse[T]:
        kwargs: dict[str, Any] = {
            "model": req.model,
            "instructions": req.system,
            "input": convert(req),
            "text_format": output,
            "max_output_tokens": req.max_tokens,
        }
        if req.effort in ("low", "medium", "high"):
            kwargs["reasoning"] = {"effort": req.effort}
        try:
            resp = self.client.responses.parse(**kwargs)
        except (self._openai.APIConnectionError, self._openai.RateLimitError, self._openai.InternalServerError) as e:
            raise ProviderError(f"[{req.task}] {type(e).__name__}: {e}", transient=True) from e
        if resp.status == "incomplete":
            raise ProviderError(f"[{req.task}] resposta incompleta: {resp.incomplete_details}")
        obj = resp.output_parsed
        if obj is None:
            raise ProviderError(f"[{req.task}] resposta sem JSON válido (possível recusa)")
        u = resp.usage
        cache = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        # input_tokens da OpenAI inclui os tokens lidos do cache; aqui separamos para o cálculo de custo
        return ProviderResponse(
            obj=obj,
            usage=Usage(input=(u.input_tokens or 0) - cache, output=u.output_tokens or 0, cache_read_tokens=cache),
            resolved_model=resp.model,
            response_id=resp.id,
        )
