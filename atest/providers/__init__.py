"""Registro de provedores de LLM. Para incluir outro (Azure OpenAI, Bedrock, Vertex, modelo local...), implemente
`Provedor` e registre com `registrar("nome", fabrica)`; depois use "nome:modelo" no config/settings.toml."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock

from .base import DocumentPart, ImagePart, Part, Provider, ProviderError, ProviderResponse, Request, TextPart, Usage

__all__ = [
    "PROVIDERS",
    "DocumentPart",
    "ImagePart",
    "Part",
    "Provider",
    "ProviderError",
    "ProviderResponse",
    "Request",
    "TextPart",
    "Usage",
    "get",
    "register",
    "split_model",
]

Factory = Callable[..., Provider]


def _anthropic(**kw) -> Provider:
    from .anthropic import AnthropicProvider

    return AnthropicProvider(**kw)


def _openai(**kw) -> Provider:
    from .openai import OpenAIProvider

    return OpenAIProvider(**kw)


def _google(**kw) -> Provider:
    from .google import GoogleProvider

    return GoogleProvider(**kw)


PROVIDERS: dict[str, Factory] = {"anthropic": _anthropic, "openai": _openai, "google": _google}
_instances: dict[str, Provider] = {}
_lock = Lock()


def register(name: str, factory: Factory) -> None:
    """Registra a fábrica de um provedor sob um nome (usado em "nome:modelo")."""
    PROVIDERS[name] = factory


def split_model(model: str, default: str = "anthropic") -> tuple[str, str]:
    """'openai:gpt-x' → ('openai', 'gpt-x'); 'claude-sonnet-5-5' → (padrao, 'claude-sonnet-5-5')."""
    if ":" in model:
        prov, mid = model.split(":", 1)
        return prov.strip().lower(), mid.strip()
    return default, model


def get(name: str, **kw) -> Provider:
    """Instância única por provedor (os SDKs reaproveitam conexões)."""
    with _lock:
        if name not in _instances:
            if name not in PROVIDERS:
                raise KeyError(f"provedor '{name}' não registrado; disponíveis: {', '.join(PROVIDERS)}")
            _instances[name] = PROVIDERS[name](**kw)
        return _instances[name]


def set_instance(name: str, provider: Provider) -> None:
    """Injeta uma instância pronta (testes, clientes com configuração própria)."""
    with _lock:
        _instances[name] = provider


def clear_instances() -> None:
    with _lock:
        _instances.clear()
