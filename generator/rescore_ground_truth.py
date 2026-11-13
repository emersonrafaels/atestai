"""Recalcula os gabaritos (data/ground_truth/*.json) com a régua atual, sem regerar chamados nem fotos.

Use depois de mudar config/rubric.toml: os gabaritos guardam notas, score, recomendação e confiança calculados com a
régua da época em que foram gerados. Este script refaz só essa parte, a partir dos apontamentos esperados:

- inclui ou retira o apontamento de valor divergente relevante, conforme o valor em questão do gabarito;
- nos chamados com escopo vago, aceita como opcionais a quantidade não verificável e o item sem foto (com o escopo
  vago, o modelo não tem como conferir quantidades nem cobertura das fotos);
- recalcula grades, score, recommendation e confidence.

    python generator/rescore_ground_truth.py            # grava
    python generator/rescore_ground_truth.py --dry-run  # só mostra o que mudaria
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from atest.config import load_settings  # noqa: E402
from atest.domain import AmountAtIssue, Extent, Finding, Rubric  # noqa: E402
from atest.photos import countable_items  # noqa: E402
from atest.score import Measures, ScoreCalculator  # noqa: E402

# com escopo vago, estes apontamentos são consequência esperada e não contam como erro na avaliação
VAGUE_SCOPE_OPTIONAL = ["unverifiable_quantity", "item_without_photo"]


def amount_at_issue(gt: dict, rubric: Rubric) -> float:
    """Valor em questão do gabarito; se não estiver gravado, calcula pelos itens (item inteiro ou só o excedente)."""
    if gt.get("amount_at_issue") is not None:
        return float(gt["amount_at_issue"])
    total = 0.0
    for item in gt.get("items", []):
        kinds = item.get("findings", [])
        specs = [rubric.finding_types[k] for k in kinds if k in rubric.finding_types]
        if any(s.amount_at_issue == AmountAtIssue.ITEM for s in specs):
            total += item["total_value"]
            continue
        excess = 0.0
        if "price_above_reference" in kinds and item.get("reference_price"):
            excess += max(0.0, (item["unit_value"] - item["reference_price"]) * item["quantity"])
        if "quantity_above_expected" in kinds and item.get("expected_quantity_max"):
            excess += max(0.0, (item["quantity"] - item["expected_quantity_max"]) * item["unit_value"])
        total += min(excess, item["total_value"])
    return round(total, 2)


IMAGE = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp")


def item_amount(item: dict, kind: str, rubric: Rubric) -> float:
    """Valor em questão de um tipo num item, como o pipeline calcula (item inteiro ou só o excedente)."""
    spec = rubric.finding_types[kind]
    if spec.amount_at_issue == AmountAtIssue.ITEM:
        return float(item["total_value"])
    if kind == "price_above_reference" and item.get("reference_price"):
        return max(0.0, (item["unit_value"] - item["reference_price"]) * item["quantity"])
    if kind == "quantity_above_expected" and item.get("expected_quantity_max"):
        return max(0.0, (item["quantity"] - item["expected_quantity_max"]) * item["unit_value"])
    return 0.0


def expected_findings(gt: dict, kinds: list[str], scorer: ScoreCalculator, total: float) -> tuple[list[Finding], Measures]:
    """Apontamentos esperados um por foto, item ou documento atingido, e as medidas do chamado.

    Assim o gabarito usa o mesmo desconto proporcional do pipeline (ex.: 3 de 6 fotos fora do escopo).
    """
    files = gt.get("attachments", {})
    photos = {n: a for n, a in files.items() if n.lower().endswith(IMAGE) and not a.get("category", "").endswith("_doc")}
    docs = {n: a for n, a in files.items() if a.get("category", "").endswith("_doc") and a.get("category") != "quote_doc"}
    items = gt.get("items", [])
    by_kind = {
        "photo_mismatch": [n for n, a in photos.items() if a.get("readable", True) and not a.get("matches_scope", True)],
        "unreadable_photo": [n for n, a in photos.items() if not a.get("readable", True)],
        "unreadable_document": [n for n, a in docs.items() if not a.get("readable", True)],
        "document_mismatch": [n for n, a in docs.items() if not a.get("matches_scope", True)],
    }
    out: list[Finding] = []
    for kind in kinds:
        if kind == "relevant_amount_at_issue" or kind not in scorer.rubric.finding_types:
            continue
        spec = scorer.rubric.finding_types[kind]
        if spec.extent == Extent.VALUE:
            hit = [i for i in items if kind in i.get("findings", [])]
            out += [scorer.finding(kind, "", f"item {i['n']}", item_amount(i, kind, scorer.rubric)) for i in hit] or [scorer.finding(kind, "")]
        elif kind == "item_without_photo":
            nums = [i["n"] for i in items if kind in i.get("findings", [])] or ([items[-1]["n"]] if items else [])
            out.append(scorer.finding(kind, "", "itens " + ", ".join(map(str, nums))))
        else:
            out += [scorer.finding(kind, "", ref) for ref in by_kind.get(kind, [])] or [scorer.finding(kind, "")]
    countable = countable_items([SimpleNamespace(**i) for i in items])
    measures = Measures(
        total_value=total, photos=len(photos), items=len(countable) or len(items), documents=len(docs),
        # o modo simulado lê um serviço pedido, sem item quando o gabarito espera "serviço pedido sem item"
        services=1, services_missing=int("scope_not_quoted" in kinds),
    )
    return out, measures


def rescore(gt: dict, scorer: ScoreCalculator) -> dict:
    """Gabarito com notas, score, recomendação e confiança refeitos pela régua atual."""
    if gt.get("recommendation") == "checklist_returned" or not gt.get("checklist_ok", True):
        return gt
    out = dict(gt)
    total = sum(i["total_value"] for i in gt.get("items", [])) or gt.get("quoted_value") or 0
    amount = amount_at_issue(gt, scorer.rubric)
    pct = 100 * amount / total if total else 0.0
    findings, measures = expected_findings(gt, gt.get("findings", []), scorer, total)
    kinds, result = scorer.expected(gt.get("findings", []), pct, findings, measures)
    out["findings"] = kinds
    if "vague_scope" in kinds:
        out["optional"] = sorted(set(gt.get("optional", [])) | set(VAGUE_SCOPE_OPTIONAL))
    out["grades"] = result.grades.model_dump()
    out["score"] = result.score
    out["recommendation"] = result.recommendation.value
    out["confidence"] = result.confidence.value
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="só mostra o que mudaria")
    args = ap.parse_args()
    cfg = load_settings()
    scorer = ScoreCalculator(cfg.rubric)
    changed = 0
    for path in sorted(cfg.ground_truth_dir.glob("*.json")):
        gt = json.loads(path.read_text(encoding="utf-8"))
        new = rescore(gt, scorer)
        if new == gt:
            continue
        changed += 1
        before = f"{gt.get('score')!s:>4} {gt.get('recommendation')}"
        after = f"{new.get('score')!s:>4} {new.get('recommendation')}"
        print(f"  {path.stem}  {before:28} -> {after}")
        if not args.dry_run:
            path.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{changed} gabarito(s) {'mudariam' if args.dry_run else 'atualizado(s)'} (régua {cfg.rubric.version})")


if __name__ == "__main__":
    main()
