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


# Tipos de erro do Pydantic → texto em português (as mensagens originais vêm em inglês).
VALIDATION_ERROR_PT = {
    "missing": "campo obrigatório",
    "extra_forbidden": "campo não reconhecido",
    "float_parsing": "número inválido",
    "float_type": "número esperado",
    "int_parsing": "número inteiro inválido",
    "int_type": "número inteiro esperado",
    "int_from_float": "número inteiro esperado",
    "bool_parsing": "valor sim/não inválido",
    "bool_type": "valor sim/não esperado",
    "string_type": "texto esperado",
    "string_too_short": "texto curto demais",
    "string_too_long": "texto longo demais",
    "date_parsing": "data inválida",
    "date_from_datetime_parsing": "data inválida",
    "date_type": "data esperada",
    "datetime_parsing": "data e hora inválidas",
    "enum": "valor não permitido",
    "literal_error": "valor não permitido",
    "greater_than": "valor abaixo do mínimo",
    "greater_than_equal": "valor abaixo do mínimo",
    "less_than": "valor acima do máximo",
    "less_than_equal": "valor acima do máximo",
    "list_type": "lista esperada",
    "dict_type": "objeto esperado",
    "value_error": "valor inválido",
}


def pt_validation_error(errors: list[dict], limit: int = 3) -> str:
    """Erros de validação do Pydantic (`e.errors()`) em português: "campo › subcampo: motivo"."""
    parts = []
    for err in errors[:limit]:
        loc = " › ".join(str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path"))
        reason = VALIDATION_ERROR_PT.get(err.get("type", ""), "valor inválido")
        if err.get("type") in ("enum", "literal_error") and (expected := (err.get("ctx") or {}).get("expected")):
            reason += f" (use {expected})"
        parts.append(f"{loc}: {reason}" if loc else reason)
    more = len(errors) - limit
    return "; ".join(parts) + (f"; e mais {more} erro(s)" if more > 0 else "")


# Tarefas do modelo (chaves internas) → nome em português (o painel usa os mesmos rótulos).
TASK_PT = {
    "identify_attachments": "Identificação dos anexos",
    "scope": "Leitura do escopo",
    "quote_review": "Orçamento × escopo",
    "photos": "Análise das fotos",
    "assessment": "Redação do parecer",
}


def error_message(e: BaseException) -> str:
    """Erro de execução para a tela, em português: "[quote_review] …" vira "Falha em Orçamento × escopo: …"."""
    text = str(e).strip()
    if m := re.match(r"^\[(\w+)\]\s*(.*)$", text, re.S):
        task, rest = m.groups()
        return f"Falha em {TASK_PT.get(task, task.replace('_', ' '))}: {rest}"
    return f"Falha na análise: {text or type(e).__name__}"
