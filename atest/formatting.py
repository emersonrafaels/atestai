"""Formatação e normalização de texto usadas em mais de uma etapa."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def brl(value: float) -> str:
    """Valor em reais no formato brasileiro: R$ 1.234,56."""
    return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def normalize_text(text: str) -> str:
    """Minúsculas, sem acentos nem pontuação, espaços simples (para comparar descrições)."""
    text = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    text = re.sub(r"\bc/\s*", "com ", text)
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


# Frase que cobra prova do serviço feito (falta/pedido + foto/evidência + depois). Na aprovação do orçamento o serviço
# ainda não foi feito: essas frases saem das observações e da mensagem ao fornecedor.
_ASK = re.compile(
    r"\b(falta|faltam|faltando|nao ha|nao tem|nenhum|nenhuma|sem fotos?|sem imagens?|ausencia|enviar|envie|reenviar|anexar|anexe|"
    r"apresentar|apresente|incluir fotos?)\b"
)
_EVIDENCE = re.compile(r"\b(fotos?|imagens?|registros?|evidencia\w*|comprova\w*|prova|termo|mostra\w*|aparece\w*)\b")
_AFTER = re.compile(
    r"\b(depois|conclu\w*|finaliza\w*|instalad\w*|organizad\w*|executad\w*|servico pronto|resultado|"
    r"apos (o|a) (servico|execucao|reparo|troca|instalacao|conserto|obra))\b"
)


def asks_for_after_service(sentence: str) -> bool:
    """A frase cobra foto, documento ou prova do serviço já feito (o "depois")?"""
    n = normalize_text(sentence)
    return bool(_ASK.search(n) and _EVIDENCE.search(n) and _AFTER.search(n))


def drop_after_service_requests(text: str) -> str:
    """Tira as frases (ou ações separadas por ';') que cobram prova do serviço feito; o resto do texto fica igual."""
    pieces = re.split(r"(?<=[.;!?])\s+", (text or "").strip())
    kept = [p for p in pieces if p and not asks_for_after_service(p)]
    if len(kept) == len([p for p in pieces if p]):
        return text
    out = " ".join(kept).strip().rstrip(";,").strip()
    if out and out[-1] not in ".!?":
        out += "."
    return out[:1].upper() + out[1:] if out else ""


def normalize_unit(unit: str) -> str:
    """Unidade comparável: "M²" e "m2" ficam iguais."""
    return unit.lower().replace("²", "2").replace(".", "").strip()


# Unidades de valor global: com quantidade 1, "un", "vb" (verba), "cj" (conjunto) e "sv" (serviço) cobram a mesma coisa.
LUMP_SUM_UNITS = {"un", "und", "unid", "unidade", "vb", "verba", "cj", "conj", "conjunto", "sv", "serv", "servico", "serviço", "gl", "global"}


def same_unit(unit: str, reference: str, quantity: float) -> bool:
    """A unidade cobrada é comparável à da referência? Iguais, ou ambas de valor global com quantidade 1."""
    a, b = normalize_unit(unit), normalize_unit(reference)
    return a == b or (quantity <= 1 and a in LUMP_SUM_UNITS and b in LUMP_SUM_UNITS)


# Termos internos (nomes de campos e valores em inglês) que o modelo às vezes escreve nos textos livres → português.
_INTERNAL_TERMS = {
    "expected_quantity_max": "quantidade máxima esperada",
    "plausible_quantity": "quantidade plausível",
    "lpu_code": "código da LPU",
    "NO_REFERENCE": "sem referência",
    "SEM_REFERENCIA": "sem referência",
    "duplicate_of": "item repetido",
    "out_of_scope": "fora do escopo",
    "to_justify": "a justificar",
    "compliant": "aderente",
    "matches_scope": "correspondência com o escopo",
    "matches_ticket": "correspondência com o chamado",
    "done_service": "serviço concluído",
    "done_justification": "justificativa",
    "has_before_photo": "foto do antes",
    "items_without_photo": "itens sem foto",
    "quantity_checks": "contagem nas fotos",
    "estimated_quantity": "quantidade estimada",
    "count_seen": "total visto",
    "covered_items": "itens evidenciados",
    "before_evidence_applicable": "foto do antes aplicável",
    "vague_scope": "escopo vago",
    "consistent_with_category_symptom": "coerência com categoria e sintoma",
    "undetermined": "indeterminado",
}
_ASSIGNMENT = re.compile(r"\s*\(\s*[a-z]+(?:_[a-z]+)+\s*=\s*[^)]*\)")  # "(expected_quantity_max = -1)"
_TERM = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _INTERNAL_TERMS), key=len, reverse=True)) + r")\b")
KEEP_VERBATIM = {"transcription"}  # transcrição (OCR) fica como está no documento


def plain_text(text: str) -> str:
    """Tira de um texto livre os nomes internos de campos e valores em inglês (ex.: '(expected_quantity_max = -1)')."""
    if " " not in text:  # valor de campo (código, enum), não texto livre
        return text
    text = _ASSIGNMENT.sub("", text)
    return _TERM.sub(lambda m: _INTERNAL_TERMS[m.group(1)], text)


def plain_language(obj: Any) -> Any:
    """Aplica plain_text em todos os textos livres de uma saída do modelo (modelos Pydantic, listas e dicionários)."""
    from enum import Enum

    from pydantic import BaseModel

    if isinstance(obj, BaseModel):
        updates = {k: plain_language(v) for k, v in obj.__dict__.items() if k not in KEEP_VERBATIM}
        return obj.model_copy(update=updates)
    if isinstance(obj, list):
        return [plain_language(v) for v in obj]
    if isinstance(obj, dict):
        return {k: plain_language(v) for k, v in obj.items()}
    if isinstance(obj, str) and not isinstance(obj, Enum):
        return plain_text(obj)
    return obj


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
    "quote_review": "Orçamento",
    "documents": "Leitura dos documentos",
    "photos": "Análise das fotos",
    "assessment": "Redação do parecer",
}


def error_message(e: BaseException) -> str:
    """Erro de execução para a tela, em português: "[quote_review] …" vira "Falha em Orçamento: …"."""
    text = str(e).strip()
    if m := re.match(r"^\[(\w+)\]\s*(.*)$", text, re.S):
        task, rest = m.groups()
        return f"Falha em {TASK_PT.get(task, task.replace('_', ' '))}: {_friendly(rest)}"
    return f"Falha na análise: {_friendly(text) or type(e).__name__}"


def _friendly(text: str) -> str:
    """Erros de rede do SDK em português: conexão recusada, sem internet ou tempo esgotado."""
    if re.search(r"APIConnectionError|ConnectError|Connection error|ConnectionError|getaddrinfo|Name or service not known", text):
        return "não foi possível conectar à API do modelo (sem internet, API fora do ar ou bloqueio de rede). Tente de novo em instantes"
    if re.search(r"APITimeoutError|ReadTimeout|timed out", text, re.I):
        return "a API do modelo não respondeu no tempo limite (fora do ar ou sobrecarregada). Tente de novo em instantes"
    return text
