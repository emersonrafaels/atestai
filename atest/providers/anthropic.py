"""Provedor Anthropic (Claude): Messages API com `messages.parse(output_format=...)` e Message Batches API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .base import DocumentPart, ImagePart, Provider, ProviderError, ProviderResponse, Request, T, TextPart, Usage


def _content(req: Request) -> list[dict]:
    blocks: list[dict] = []
    for p in req.parts:
        if isinstance(p, TextPart):
            blocks.append({"type": "text", "text": p.text})
        elif isinstance(p, ImagePart):
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": p.mime, "data": p.b64}})
        elif isinstance(p, DocumentPart):
            blocks.append({"type": "document", "title": p.title, "source": {"type": "base64", "media_type": p.mime, "data": p.b64}})
    return blocks


class AnthropicProvider(Provider):
    """Claude pela API da Anthropic: saída estruturada, cache do prompt de sistema e Message Batches."""

    name = "anthropic"
    supports_batch = True

    def __init__(self, timeout_s: float = 180, max_retries: int = 4, client: Any = None):
        import anthropic

        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic(max_retries=max_retries, timeout=timeout_s)

    def _params(self, req: Request) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            # prompt de sistema com cache: em lote, instruções e LPU se repetem chamado a chamado
            "system": [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": _content(req)}],
        }
        if req.effort:
            params["output_config"] = {"effort": req.effort}
        return params

    @staticmethod
    def _usage(u: Any) -> Usage:
        return Usage(
            input=u.input_tokens or 0,
            output=u.output_tokens or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )

    @staticmethod
    def _check(stop_reason: str | None, req: Request) -> None:
        if stop_reason == "max_tokens":
            raise ProviderError(f"[{req.task}] resposta cortada em max_tokens={req.max_tokens}")
        if stop_reason == "refusal":
            raise ProviderError(f"[{req.task}] o modelo recusou a solicitação")

    def generate(self, req: Request, output: type[T]) -> ProviderResponse[T]:
        try:
            resp = self.client.messages.parse(**self._params(req), output_format=output)
        except (self._anthropic.APIConnectionError, self._anthropic.RateLimitError, self._anthropic.InternalServerError) as e:
            raise ProviderError(f"[{req.task}] {type(e).__name__}: {e}", transient=True) from e
        self._check(resp.stop_reason, req)
        if resp.parsed_output is None:
            raise ProviderError(f"[{req.task}] resposta sem JSON válido")
        return ProviderResponse(obj=resp.parsed_output, usage=self._usage(resp.usage), resolved_model=resp.model, response_id=resp.id)

    # ------------------------------------------------------------------ Message Batches API
    def create_batch(self, items: list[tuple[str, Request, type[BaseModel]]]) -> str:
        requests = []
        for custom_id, req, output in items:
            params = self._params(req)
            params["output_config"] = {
                **params.get("output_config", {}),
                "format": {"type": "json_schema", "schema": self._anthropic.transform_schema(output)},
            }
            requests.append({"custom_id": custom_id, "params": params})
        return self.client.messages.batches.create(requests=requests).id

    def batch_finished(self, batch_id: str) -> bool:
        return self.client.messages.batches.retrieve(batch_id).processing_status == "ended"

    def batch_results(self, batch_id: str, outputs: dict[str, type[BaseModel]]) -> dict[str, ProviderResponse | Exception]:
        out: dict[str, ProviderResponse | Exception] = {}
        for r in self.client.messages.batches.results(batch_id):
            output = outputs.get(r.custom_id)
            if output is None:
                continue
            try:
                if r.result.type != "succeeded":
                    raise ProviderError(f"requisição do lote terminou como '{r.result.type}'", transient=r.result.type == "expired")
                msg = r.result.message
                if msg.stop_reason in ("max_tokens", "refusal"):
                    raise ProviderError(f"lote: stop_reason={msg.stop_reason}")
                text = "".join(b.text for b in msg.content if b.type == "text")
                out[r.custom_id] = ProviderResponse(
                    obj=output.model_validate_json(text),
                    usage=self._usage(msg.usage),
                    resolved_model=msg.model,
                    response_id=msg.id,
                    via_batch=True,
                    batch_id=batch_id,
                )
            except Exception as e:
                out[r.custom_id] = e
        return out
