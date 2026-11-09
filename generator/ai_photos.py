"""Gera fotos fotorrealistas das cenas do dataset com um modelo de imagem e grava na pasta do perfil
(data/real_photos/<chave>/ ou, com --profile itau, data/real_photos_itau/<chave>/).

Depois rode de novo o gerador do conjunto: as cenas passam a usar essas fotos no lugar dos desenhos.
Detalhes em generator/real_photos.py.

Uso:
    python generator/ai_photos.py --list                                  # o que já existe em cada pasta
    python generator/ai_photos.py                                         # completa todas as pastas até PER_SCENE fotos
    python generator/ai_photos.py --only outlets__burned --count 2        # só uma chave
    python generator/ai_photos.py --profile itau --from-needs --dry-run   # conjunto Itaú: quantas e quanto custa
    python generator/ai_photos.py --profile itau --from-needs             # conjunto Itaú: gera o que falta

A chave vem de config/.secrets.toml (openai_api_key ou gemini_api_key) ou de variável de ambiente. Cada imagem gerada é
cobrada pelo provedor: use --dry-run para ver o custo estimado antes.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import real_photos  # noqa: E402

from atest.config import load_settings  # noqa: E402

# ------------------------------------------------------------------ parâmetros (troque aqui)
PROVIDER = "openai"  # "openai" ou "google"
MODEL = {"openai": "gpt-image-2-2026-04-21", "google": "imagen-4.0-generate-001"}  # snapshot datado: resultado reprodutível
PER_SCENE = 12  # o conjunto de validação usa até ~10 fotos da mesma cena; sobra margem
OPENAI_SIZE = "1536x1024"  # paisagem, como foto de celular deitado
OPENAI_QUALITY = "medium"
PRICE_USD = {"openai": 0.063, "google": 0.04}  # por imagem (gpt-image-1 medium 1536x1024; Imagen 4); confira a tabela atual


def generate_openai(prompt: str, n: int) -> list[bytes]:
    from openai import OpenAI

    client = OpenAI()
    out = []
    for _ in range(n):  # uma por requisição: variações independentes
        r = client.images.generate(model=MODEL["openai"], prompt=prompt, size=OPENAI_SIZE, quality=OPENAI_QUALITY, n=1)
        out.append(base64.b64decode(r.data[0].b64_json))
    return out


def generate_google(prompt: str, n: int) -> list[bytes]:
    from google import genai
    from google.genai import types

    client = genai.Client()
    out: list[bytes] = []
    while len(out) < n:
        r = client.models.generate_images(
            model=MODEL["google"], prompt=prompt, config=types.GenerateImagesConfig(number_of_images=min(4, n - len(out)), aspect_ratio="4:3")
        )
        out += [g.image.image_bytes for g in r.generated_images]
    return out


GENERATORS = {"openai": generate_openai, "google": generate_google}


def missing(targets: dict[str, int]) -> dict[str, int]:
    """chave → quantas fotos faltam para chegar à meta (o que já está na pasta conta)."""
    have = real_photos.status()
    return {k: t - have[k][0] for k, t in targets.items() if t - have[k][0] > 0}


def complete(todo: dict[str, int]) -> None:
    load_settings()  # coloca as chaves de config/.secrets.toml nas variáveis de ambiente
    failed: list[str] = []
    for k, n in todo.items():
        folder = real_photos.ROOT / k
        folder.mkdir(parents=True, exist_ok=True)
        print(f"{k}: gerando {n} foto(s) com {PROVIDER}:{MODEL[PROVIDER]}…", flush=True)
        t0 = time.time()
        try:
            images = GENERATORS[PROVIDER](real_photos.STYLE + real_photos.CATALOG[k], n)
        except Exception as e:  # noqa: BLE001 — uma cena recusada ou com erro não derruba o resto
            print(f"  erro: {e}")
            failed.append(k)
            continue
        for i, data in enumerate(images):
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.save(folder / f"ia_{PROVIDER}_{int(t0)}_{i:02d}.jpg", quality=88)
        print(f"  ok em {time.time() - t0:.0f} s")
    if failed:
        sys.exit(f"cenas com erro (rode de novo com --only): {' '.join(failed)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="default", choices=sorted(real_photos.PROFILES))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", nargs="*", help="só estas chaves")
    ap.add_argument("--count", type=int, help="meta de fotos por chave (padrão PER_SCENE)")
    ap.add_argument("--from-needs", action="store_true", help="meta por chave vinda de _needs.json (build_itau_dataset.py --needs)")
    ap.add_argument("--dry-run", action="store_true", help="só mostra o que seria gerado e o custo estimado")
    ap.add_argument("--model", help=f"modelo de imagem (padrão {MODEL[PROVIDER]})")
    a = ap.parse_args()
    if a.model:
        MODEL[PROVIDER] = a.model
    real_photos.use_profile(a.profile)

    if a.list:
        for k, (n, used) in real_photos.status().items():
            print(f"{k:32s} {n:3d} foto(s), {used} em uso")
        sys.exit(0)

    if a.from_needs:
        needs_file = real_photos.ROOT / "_needs.json"
        if not needs_file.exists():
            sys.exit(f"{needs_file} não existe: rode antes o gerador do conjunto com --needs")
        targets = json.loads(needs_file.read_text(encoding="utf-8"))
        if a.only:
            targets = {k: v for k, v in targets.items() if k in a.only}
    else:
        targets = {k: a.count or PER_SCENE for k in (a.only or real_photos.CATALOG)}
    unknown = [k for k in targets if k not in real_photos.CATALOG]
    if unknown:
        sys.exit(f"chave(s) sem descrição no catálogo do perfil {a.profile}: {', '.join(unknown)}")

    todo = missing(targets)
    total = sum(todo.values())
    print(f"perfil {a.profile} → {real_photos.ROOT}")
    for k, n in todo.items():
        print(f"  {k:28s} +{n}")
    print(f"{total} imagem(ns) com {PROVIDER}:{MODEL[PROVIDER]}, custo estimado US$ {total * PRICE_USD[PROVIDER]:.2f}")
    if not a.dry_run and total:
        complete(todo)
