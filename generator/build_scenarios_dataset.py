"""Gera o catálogo de cenários de teste (0300xxxx): um chamado por tipo de problema, com defeitos FORÇADOS.

Os conjuntos de validação e Itaú sorteiam os defeitos; aqui cada cenário é fixo e nomeado, para garantir que todo tipo
de problema (escopo mal preenchido, orçamento com vários erros, foto de outro ambiente...) tenha pelo menos um
chamado, fácil de achar. O gabarito sai da régua, como na validação, e grava o cenário (`scenario`) para o painel.

No fim, escreve `docs/cenarios.md`: o catálogo e, para cada tipo de cenário, os chamados de TODOS os conjuntos que o
trazem (etiquetas de `atest/scenarios.py`). Rode depois dos outros geradores:

    python generator/build_demo_dataset.py --clean
    python generator/build_validation_dataset.py
    python generator/build_itau_dataset.py
    python generator/build_scenarios_dataset.py           # gera os chamados e a documentação
    python generator/build_scenarios_dataset.py --doc     # só reescreve docs/cenarios.md
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_itau_dataset import _rmtree  # noqa: E402
from build_validation_dataset import CFG, MODELS, ROOT, ValidationGenerator  # noqa: E402

from atest.repository import list_tickets, load_ground_truth, load_ticket  # noqa: E402
from atest.scenarios import GROUPS, TAGS, tags_for  # noqa: E402

PREFIX, DATASET = "0300", "scenarios"
DOC = ROOT.parent / "docs" / "cenarios.md"

# (id, título, o que o chamado testa, modelo de serviço, defeitos). A ordem importa: o chamado limpo de um modelo vem
# antes do cenário que reaproveita foto dele.
SCENARIOS: list[tuple[str, str, str, str, list[str]]] = [
    ("clean_building", "Chamado limpo (predial)", "Pintura sem nenhum problema: deve ser aprovado.", "painting", []),
    ("clean_security", "Chamado limpo (segurança)", "Câmera desfocada, serviço comprovado: deve ser aprovado.", "camera", []),
    ("clean_quote_stage", "Aprovação de orçamento limpa", "Orçamento antes da execução, sem problemas.", "sink", []),
    ("scope_vague", "Escopo vago", 'O texto não diz o que fazer nem onde ("Verificar ... Urgente.").', "hvac", ["vague"]),
    ("scope_inconsistent", "Escopo incoerente", "O sintoma informado não combina com a categoria.", "outlets", ["inconsistent"]),
    (
        "scope_bad",
        "Escopo mal preenchido",
        "Vago e incoerente ao mesmo tempo: dois redutores de confiança levam à análise detalhada.",
        "painting",
        ["vague", "inconsistent"],
    ),
    ("quote_out_of_scope", "Item fora do escopo", "Orçamento cobra serviço que não foi pedido.", "infiltration", ["out_of_scope"]),
    ("quote_replacement", "Troca sem justificativa", "Pedido de limpeza e ajuste, orçamento cobra câmera nova.", "camera", ["replacement"]),
    ("quote_price", "Preço acima da referência", "Um item acima da LPU + tolerância.", "door", ["price"]),
    ("quote_quantity", "Quantidade acima do esperado", "Mais lâmpadas do que o escopo pede.", "lamps", ["quantity"]),
    ("quote_duplicate", "Item duplicado", "O mesmo item cobrado em duas linhas.", "sensor", ["duplicate"]),
    ("quote_spreadsheet", "Planilha divergente", "Valor ou sintoma da planilha diferente do chamado.", "preventive", ["spreadsheet"]),
    (
        "quote_multiple",
        "Orçamento com vários erros",
        "Fora do escopo, preço acima, quantidade acima e duplicidade no mesmo orçamento.",
        "hvac",
        ["out_of_scope", "price", "quantity", "duplicate"],
    ),
    (
        "quote_multiple_quote_stage",
        "Orçamento com erros na aprovação",
        "Etapa de orçamento (antes da execução) com item fora do escopo e preço acima.",
        "sink",
        ["out_of_scope", "price"],
    ),
    ("photo_mismatch", "Foto de outro ambiente", "Uma foto mostra outro cômodo ou a fachada.", "painting", ["does_not_match"]),
    ("photo_no_after", "Sem foto do depois", "Nenhuma foto prova o serviço concluído.", "camera", ["no_after"]),
    (
        "photo_no_after_mismatch",
        "Foto do depois de outro ambiente",
        "Falta a prova do serviço e há foto de outro ambiente: a régua desconta só uma vez (absorção).",
        "camera",
        ["no_after", "does_not_match"],
    ),
    ("photo_no_before", "Sem foto do antes", "Não há registro do estado anterior (Fase 2).", "hvac", ["no_before"]),
    ("photo_unreadable", "Foto ilegível", "Foto escura e tremida (Fase 2).", "outlets", ["unreadable"]),
    ("photo_reused", "Foto reaproveitada", "Foto de um chamado anterior: trava de integridade (Fase 2).", "painting", ["reused"]),
    ("photo_dated_before", "Foto com data anterior", "EXIF anterior à abertura do chamado.", "door", ["date_before"]),
    ("checklist_incomplete", "Checklist incompleto", "Falta documento obrigatório: volta antes da análise.", "sensor", ["checklist"]),
    (
        "everything",
        "Problemas em todas as validações",
        "Escopo vago, item fora do escopo, preço acima, foto de outro ambiente e foto ilegível.",
        "lamps",
        ["vague", "out_of_scope", "price", "does_not_match", "unreadable"],
    ),
]

REC_PT = {
    "approve": "Aprovar",
    "approve_with_caveats": "Aprovar com ressalvas",
    "return_to_supplier": "Devolver ao fornecedor",
    "return_locked": "Devolver com trava",
    "detailed_review": "Análise detalhada",
    "checklist_returned": "Devolvido no checklist",
}
DATASET_PT = {"demo": "Demonstração", "validation": "Validação", "itau": "Itaú", "scenarios": "Cenários", "uploaded": "Enviados"}


def clean() -> None:
    for p in (ROOT / "tickets").glob(f"{PREFIX}*"):
        _rmtree(p)
    for p in (ROOT / "ground_truth").glob(f"{PREFIX}*.json"):
        p.unlink()


def build() -> list[dict]:
    clean()
    templates = {m.name: m for m in MODELS}
    g = ValidationGenerator(1, seed=3030, prefix=PREFIX, dataset=DATASET, day0=date(2026, 10, 20))
    g.index_existing()
    out = []
    for i, (sid, title, description, template, defects) in enumerate(SCENARIOS, 1):
        tid = f"{PREFIX}{i:04d}"
        scenario = {"id": sid, "title": title, "description": description}
        out.append(g.one_ticket(tid, templates[template], 1, g.day0 + timedelta(days=i), defects=defects, scenario=scenario))
        print(f"  {tid}  {title:40} → {out[-1]['recommendation']}")
    return out


def write_doc() -> Path:
    """docs/cenarios.md: catálogo 0300… e, por tipo de cenário, os chamados de todos os conjuntos."""
    rubric = CFG.rubric
    label = {k: t.description for k, t in rubric.finding_types.items()}
    by_tag: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    catalog = []
    for folder in list_tickets(ROOT / "tickets"):
        gt = load_ground_truth(ROOT / "ground_truth", folder.name)
        if gt is None:
            continue
        dataset = load_ticket(folder).data.dataset
        for tag in tags_for(gt, rubric):
            by_tag[tag][dataset].append(folder.name)
        if gt.scenario:
            catalog.append((folder.name, gt))

    lines = [
        "# Cenários de teste",
        "",
        "Gerado por `python generator/build_scenarios_dataset.py` (não edite à mão). No painel, a aba **Cenários** mostra o mesmo",
        "catálogo, com filtro e seleção dos chamados para analisar.",
        "",
        "## Catálogo (um chamado por cenário, conjunto `scenarios`)",
        "",
        "| Chamado | Cenário | O que testa | Esperado | Score | Apontamentos esperados |",
        "|---|---|---|---|---|---|",
    ]
    for tid, gt in catalog:
        findings = ", ".join(label.get(k, k) for k in gt.findings) or "—"
        score = "—" if gt.score is None else str(gt.score)
        lines.append(
            f"| `{tid}` | {gt.scenario['title']} | {gt.scenario['description']} | {REC_PT[gt.recommendation.value]} | {score} | {findings} |"
        )
    lines += ["", "## Por tipo de cenário, em todos os conjuntos", ""]
    for group, group_label in GROUPS.items():
        lines += [f"### {group_label}", "", "| Cenário | Qtd. | Chamados |", "|---|---|---|"]
        for t in (t for t in TAGS if t.group == group):
            found = by_tag.get(t.id, {})
            n = sum(len(v) for v in found.values())
            ids = "; ".join(f"{DATASET_PT.get(ds, ds)}: " + ", ".join(f"`{x}`" for x in sorted(v)) for ds, v in sorted(found.items())) or "—"
            lines.append(f"| **{t.label}**<br>{t.description} | {n} | {ids} |")
        lines.append("")
    DOC.write_text("\n".join(lines), encoding="utf-8")
    return DOC


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", action="store_true", help="só reescreve docs/cenarios.md")
    a = ap.parse_args()
    if not a.doc:
        summary = build()
        print(f"{len(summary)} cenários (0300xxxx) em {ROOT / 'tickets'}")
    print("documentação →", write_doc())
