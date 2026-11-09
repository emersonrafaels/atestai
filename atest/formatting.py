"""Formatação e normalização de texto usadas em mais de uma etapa."""

from __future__ import annotations

import re
import unicodedata


def brl(value: float) -> str:
    """Valor em reais no formato brasileiro: R$ 1.234,56."""
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def normalize_text(text: str) -> str:
    """Minúsculas, sem acentos nem pontuação, espaços simples (para comparar descrições)."""
    text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    text = re.sub(r"\bc/\s*", "com ", text)
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


def normalize_unit(unit: str) -> str:
    """Unidade comparável: "M²" e "m2" ficam iguais."""
    return unit.lower().replace("²", "2").replace(".", "").strip()
