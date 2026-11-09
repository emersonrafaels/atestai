"""Teste rápido do provedor configurado (Anthropic, OpenAI, Gemini ou IARA) antes de rodar o lote.

Usa o modelo principal de config/settings.toml (ex.: "anthropic:claude-sonnet-5-5", "openai:<modelo>", "iara:gpt-4.1")
e as chaves de config/.secrets.toml. Rode:  python examples/api_smoke_test.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic import BaseModel, Field  # noqa: E402

from atest import providers  # noqa: E402
from atest.attachments import image  # noqa: E402
from atest.config import load_settings, missing_keys  # noqa: E402
from atest.providers import Request, TextPart  # noqa: E402


class ScopeReading(BaseModel):
    category_coherent: bool = Field(description="O escopo é coerente com a categoria informada?")
    vague_scope: bool
    reason: str


class PhotoReading(BaseModel):
    what_it_shows: str
    matches_scope: Literal["yes", "no", "partial", "undetermined"]
    reason: str


def main() -> None:
    cfg = load_settings()
    if missing := missing_keys(cfg):
        raise SystemExit(f"Faltam credenciais para: {', '.join(missing)}. Preencha config/.secrets.toml ou as variáveis de ambiente.")
    name, model = providers.split_model(cfg.models.main, cfg.llm.default_provider)
    prov = providers.get(name, timeout_s=cfg.llm.timeout_s, max_retries=cfg.llm.max_retries, **cfg.llm.provider_options.get(name, {}))
    print(f"Provedor {name} · modelo {model}")

    t = time.perf_counter()
    r = prov.generate(
        Request(
            task="test",
            system="Você confere chamados de manutenção de agências bancárias.",
            model=model,
            max_tokens=500,
            parts=[
                TextPart(
                    "Categoria: Serralheria e portas. Sintoma: Falha mecânica. Escopo: "
                    "'Verificar porta. Urgente.' O escopo é vago demais para conferir um orçamento?"
                )
            ],
        ),
        ScopeReading,
    )
    print(f"[1] {time.perf_counter() - t:.1f}s · {r.resolved_model} · tokens {r.usage.input}+{r.usage.output}\n{r.obj.model_dump_json(indent=2)}")

    photo = ROOT / "data/tickets/00482193/attachments/IMG_20260928_113002.jpg"  # fachada externa
    t = time.perf_counter()
    r = prov.generate(
        Request(
            task="test",
            system="Você confere fotos de serviços de manutenção.",
            model=model,
            max_tokens=600,
            parts=[TextPart("Escopo: 'Repintura de paredes e teto do backoffice (aprox. 240 m²).' Esta foto comprova o escopo?"), image(photo)],
        ),
        PhotoReading,
    )
    print(f"\n[2] {time.perf_counter() - t:.1f}s · tokens {r.usage.input}+{r.usage.output}\n{r.obj.model_dump_json(indent=2)}")
    print("\nEsperado: escopo_vago = true no [1]; corresponde_escopo = 'nao' no [2] (fachada externa, escopo interno).")


if __name__ == "__main__":
    main()
