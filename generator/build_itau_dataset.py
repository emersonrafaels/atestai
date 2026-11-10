"""Gera o conjunto ITAU: chamados de agências Itaú com fotos fotorrealistas (geradas por IA), no lugar dos desenhos.

Mesma mecânica do conjunto de validação (modelos de serviço, defeitos sorteados, gabarito pela régua), com:
- ids 0200xxxx e `dataset = "itau"`: 20 de execução e, depois, 21 de Aprovação de Orçamento (`--quote-n`);
- agências no padrão Itaú (códigos e nomes fictícios; fornecedores, CNPJs e valores também fictícios);
- fotos da biblioteca `data/real_photos_itau/<chave>/` (perfil "itau" de generator/real_photos.py), em modo strict:
  se faltar foto, para com erro em vez de cair no desenho.

Fluxo:
    python generator/build_itau_dataset.py --needs                        # quantas fotos cada cena precisa
    python generator/ai_photos.py --profile itau --from-needs --dry-run   # quantas imagens e custo estimado
    python generator/ai_photos.py --profile itau --from-needs             # gera as fotos (cobrado pela OpenAI)
    python generator/build_itau_dataset.py                                # gera os chamados

Ficam desenhados (o texto precisa bater com o chamado): etiqueta da luminária, teclado da central, termo de conclusão,
relatório de preventiva e o texto sobreposto às imagens de CFTV (a imagem da câmera em si é foto).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import real_photos  # noqa: E402
from build_validation_dataset import QUOTE_STAGE_MODELS, ROOT, ValidationGenerator  # noqa: E402

PREFIX = "0200"
DATASET = "itau"
PER_TEMPLATE = 2  # 10 modelos de serviço × 2 = 20 chamados
QUOTE_PER_TEMPLATE = 3  # + 7 modelos na etapa de Aprovação de Orçamento × 3 = 21 chamados (02000021 em diante)
ITAU_BRANCHES = [
    ("3120", "Itaú Ag. Av. Paulista"),
    ("4418", "Itaú Ag. Pinheiros"),
    ("2273", "Itaú Ag. Faria Lima"),
    ("5531", "Itaú Ag. Moema"),
    ("6084", "Itaú Ag. Tatuapé"),
    ("3967", "Itaú Ag. Santo Amaro"),
    ("7142", "Itaú Ag. Liberdade"),
    ("2809", "Itaú Ag. Vila Madalena"),
    ("8356", "Itaú Ag. Brooklin"),
    ("4675", "Itaú Ag. Aclimação"),
    ("9013", "Itaú Ag. Água Branca"),
    ("6290", "Itaú Ag. Itaim Bibi"),
]
NEEDS_FILE = real_photos.PROFILES["itau"][0] / "_needs.json"


def _rmtree(p: Path, tries: int = 10) -> None:
    """Apaga a pasta. No OneDrive as pastas podem ficar somente leitura ou presas por um instante: tira o atributo e
    tenta de novo."""

    def writable(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    for i in range(tries):
        try:
            shutil.rmtree(p, onexc=writable)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.5 * (i + 1))


def clean() -> None:
    for p in (ROOT / "tickets").glob(f"{PREFIX}*"):
        _rmtree(p)
    for p in (ROOT / "ground_truth").glob(f"{PREFIX}*.json"):
        p.unlink()


def build(n: int, quote_n: int = QUOTE_PER_TEMPLATE) -> list[dict]:
    clean()
    # semente escolhida para que a 2ª rodada (a 1ª de cada modelo sai limpa) cubra defeitos variados: checklist,
    # reaproveitamento, foto de outro ambiente, falta do depois, troca sem justificativa, preço, quantidade...
    g = ValidationGenerator(n, seed=2083, prefix=PREFIX, dataset=DATASET, branches=ITAU_BRANCHES, day0=date(2026, 10, 25), realistic=True)
    g.index_existing()
    # os chamados de orçamento vêm depois: os 20 de execução saem iguais com ou sem eles
    return g.generate() + g.generate(models=QUOTE_STAGE_MODELS, n=quote_n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=PER_TEMPLATE, help="chamados por modelo de serviço (10 modelos)")
    ap.add_argument("--quote-n", type=int, default=QUOTE_PER_TEMPLATE, help="chamados por modelo na Aprovação de Orçamento (7 modelos)")
    ap.add_argument("--needs", action="store_true", help="só calcula quantas fotos cada cena precisa e grava _needs.json")
    a = ap.parse_args()

    if a.needs:
        real_photos.use_profile("itau", mode="record")
        build(a.n, a.quote_n)
        clean()  # os chamados desta passada saíram com desenhos; não ficam
        needs = real_photos.needs()
        NEEDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        NEEDS_FILE.write_text(json.dumps(needs, indent=1), encoding="utf-8")
        print(f"{sum(needs.values())} foto(s) em {len(needs)} cena(s) → {NEEDS_FILE}")
        for k, v in needs.items():
            print(f"  {k:28s} {v:3d}")
        sys.exit(0)

    real_photos.use_profile("itau", mode="strict")
    try:
        summary = build(a.n, a.quote_n)
    except real_photos.PhotoShortage as e:
        clean()
        sys.exit(f"faltam fotos: {e}\nRode antes: python generator/build_itau_dataset.py --needs e python generator/ai_photos.py --profile itau --from-needs")
    print(f"{len(summary)} chamados Itaú ({PREFIX}xxxx) em {ROOT / 'tickets'}")
    print("recomendações esperadas:", dict(Counter(r["recommendation"] for r in summary)))
    print("por etapa:", dict(Counter("orçamento" if r["model"].endswith("_quote") or r["model"] == "sink" else "execução" for r in summary)))
    print("defeitos injetados:", dict(Counter(d for r in summary for d in r["defects"])))
