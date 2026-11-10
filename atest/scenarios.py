"""Cenários de teste: etiquetas que dizem que tipo de problema cada chamado com gabarito traz.

As etiquetas saem do gabarito (apontamentos e recomendação esperados), então valem para todos os conjuntos:
demonstração, validação, Itaú e o catálogo de cenários (`0300…`, gerado por `generator/build_scenarios_dataset.py`,
com um chamado por cenário). O painel usa isso na aba Cenários; o gerador, para escrever `docs/cenarios.md`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .domain import Rubric
from .repository import GroundTruth


@dataclass(frozen=True)
class ScenarioTag:
    """Tipo de cenário: grupo, nome, explicação e a regra que reconhece o cenário no gabarito."""

    id: str
    group: str
    label: str
    description: str
    test: Callable[[GroundTruth, dict[str, set[str]]], bool]


GROUPS = {
    "result": "Resultado esperado",
    "scope": "Escopo",
    "quote": "Orçamento",
    "photos": "Fotos",
    "checklist": "Checklist",
    "combined": "Combinações",
}


def _has(*kinds: str) -> Callable[[GroundTruth, dict[str, set[str]]], bool]:
    return lambda g, _v: any(k in g.findings for k in kinds)


def _rec(rec: str) -> Callable[[GroundTruth, dict[str, set[str]]], bool]:
    return lambda g, _v: g.recommendation.value == rec


TAGS: list[ScenarioTag] = [
    # resultado esperado
    ScenarioTag(
        "clean", "result", "Chamado limpo", "Nenhum apontamento esperado: o Atest.AI deve aprovar.", lambda g, _v: not g.findings and g.checklist_ok
    ),
    ScenarioTag("expect_caveats", "result", "Aprovar com ressalvas", "Problemas leves: score entre 70 e 84.", _rec("approve_with_caveats")),
    ScenarioTag("expect_return", "result", "Devolver ao fornecedor", "Score abaixo de 70.", _rec("return_to_supplier")),
    ScenarioTag("expect_locked", "result", "Devolver com trava", "Trava de integridade (foto reaproveitada).", _rec("return_locked")),
    ScenarioTag("expect_detailed", "result", "Análise detalhada", "Confiança baixa: entrada insuficiente para concluir.", _rec("detailed_review")),
    # escopo
    ScenarioTag(
        "scope_bad",
        "scope",
        "Escopo mal preenchido",
        "Escopo vago ou incoerente com a categoria e o sintoma.",
        _has("vague_scope", "inconsistent_scope"),
    ),
    ScenarioTag("scope_vague", "scope", "Escopo vago", "Não dá para saber o que fazer, onde ou em quê.", _has("vague_scope")),
    ScenarioTag(
        "scope_inconsistent", "scope", "Escopo incoerente", "O sintoma informado não bate com a categoria ou o texto.", _has("inconsistent_scope")
    ),
    # orçamento
    ScenarioTag(
        "quote_multiple",
        "quote",
        "Orçamento com vários erros",
        "Dois ou mais tipos de problema no orçamento.",
        lambda g, v: len(v.get("quote", set())) >= 2,
    ),
    ScenarioTag("quote_out_of_scope", "quote", "Item fora do escopo", "Serviço, local ou equipamento que não foi pedido.", _has("out_of_scope_item")),
    ScenarioTag(
        "quote_replacement",
        "quote",
        "Troca sem justificativa",
        "Troca de peça quando o pedido era ajuste ou reparo.",
        _has("unjustified_replacement"),
    ),
    ScenarioTag("quote_price", "quote", "Preço acima da referência", "Valor unitário acima da LPU + tolerância.", _has("price_above_reference")),
    ScenarioTag("quote_quantity", "quote", "Quantidade acima do esperado", "Mais do que o escopo permite.", _has("quantity_above_expected")),
    ScenarioTag("quote_duplicate", "quote", "Item duplicado", "A mesma coisa cobrada duas vezes.", _has("duplicate_item")),
    ScenarioTag(
        "quote_spreadsheet", "quote", "Planilha divergente", "Planilha diferente do chamado (valor ou sintoma).", _has("spreadsheet_mismatch")
    ),
    # fotos
    ScenarioTag("photo_mismatch", "photos", "Foto de outro ambiente", "Foto que não corresponde ao escopo.", _has("photo_mismatch")),
    ScenarioTag("photo_no_after", "photos", "Sem foto do depois", "Nenhuma foto prova o serviço concluído.", _has("missing_after_photo")),
    ScenarioTag("photo_no_before", "photos", "Sem foto do antes", "Nenhuma foto do estado anterior (Fase 2).", _has("missing_before_photo")),
    ScenarioTag("photo_unreadable", "photos", "Foto ilegível", "Foto escura ou tremida (Fase 2).", _has("unreadable_photo")),
    ScenarioTag("photo_reused", "photos", "Foto reaproveitada", "Foto de outro chamado (Fase 2, trava).", _has("reused_photo")),
    ScenarioTag("photo_dated_before", "photos", "Foto com data anterior", "Data EXIF anterior à abertura do chamado.", _has("photo_dated_before")),
    # checklist
    ScenarioTag(
        "checklist_incomplete",
        "checklist",
        "Checklist incompleto",
        "Falta documento obrigatório: volta antes da análise.",
        lambda g, _v: not g.checklist_ok,
    ),
    # combinações
    ScenarioTag(
        "multi_validation",
        "combined",
        "Problemas em várias validações",
        "Apontamentos em duas ou mais validações (escopo, orçamento, fotos).",
        lambda g, v: len(v) >= 2,
    ),
    ScenarioTag(
        "quote_stage", "combined", "Aprovação de orçamento", "Chamado na etapa de orçamento (antes da execução).", lambda g, _v: g.moment == "quote"
    ),
]


def validations_with_findings(g: GroundTruth, rubric: Rubric) -> dict[str, set[str]]:
    """Validação → tipos de apontamento esperados nela."""
    out: dict[str, set[str]] = {}
    for kind in g.findings:
        spec = rubric.finding_types.get(kind)
        if spec:
            out.setdefault(spec.validation.value, set()).add(kind)
    return out


def tags_for(g: GroundTruth | None, rubric: Rubric) -> list[str]:
    """Etiquetas de cenário de um chamado (vazio se não há gabarito)."""
    if g is None:
        return []
    by_validation = validations_with_findings(g, rubric)
    return [t.id for t in TAGS if t.test(g, by_validation)]


def catalog() -> list[dict[str, str]]:
    """Definições das etiquetas, na ordem de exibição (para a API e a documentação)."""
    return [{"id": t.id, "group": t.group, "group_label": GROUPS[t.group], "label": t.label, "description": t.description} for t in TAGS]
