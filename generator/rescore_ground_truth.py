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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from atest.config import load_settings  # noqa: E402
from atest.domain import AmountAtIssue, Rubric  # noqa: E402
from atest.score import ScoreCalculator  # noqa: E402

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


def rescore(gt: dict, scorer: ScoreCalculator) -> dict:
    """Gabarito com notas, score, recomendação e confiança refeitos pela régua atual."""
    if gt.get("recommendation") == "checklist_returned" or not gt.get("checklist_ok", True):
        return gt
    out = dict(gt)
    total = sum(i["total_value"] for i in gt.get("items", [])) or gt.get("quoted_value") or 0
    amount = amount_at_issue(gt, scorer.rubric)
    pct = 100 * amount / total if total else 0.0
    kinds, result = scorer.expected(gt.get("findings", []), pct)
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
