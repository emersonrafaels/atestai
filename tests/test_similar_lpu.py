"""Item Não LPU com similar na LPU (ex.: parede removível → parede de drywall): apontamento com o preço do similar."""

from atest.documents import DocumentStage
from atest.domain import QuoteItem, Recommendation
from atest.quote import QuoteStage
from atest.repository import load_ticket, read_ticket_quote
from atest.score import ScoreCalculator

from .test_rules import review


def _quote(cfg, *items: QuoteItem):
    ch = load_ticket(cfg.tickets_dir / "04159084")  # SETA, planilha com a coluna LPU
    q = read_ticket_quote(ch)
    return ch, q.model_copy(update={"items": list(items)})


def _wall(unit_value: float, lpu: bool = False, unit: str = "m²") -> QuoteItem:
    return QuoteItem(
        n=1,
        description="Parede removível",
        unit=unit,
        lpu=lpu,
        quantity=10,
        unit_value=unit_value,
        total_value=10 * unit_value,
    )


def _flag(cfg, ref, item, similar="DRY-001", **by_item):
    ch, q = _quote(cfg, item)
    st = QuoteStage(cfg, ref, ScoreCalculator(ref.rubric))
    conf = review(q, {1: "NO_REFERENCE"}, {1: {"similar": similar, **by_item}})
    return st.flag(ch, q, conf)


def test_non_lpu_item_with_similar_is_flagged_with_the_excess(cfg, ref):
    items, findings, _ = _flag(cfg, ref, _wall(200.0))
    f = next(f for f in findings if f.kind == "similar_lpu_item")
    assert f.reference == "item 1" and f.caveats
    assert "DRY-001" in f.evidence and "drywall" in f.evidence.lower()
    assert f.amount_at_issue == 550.0  # (200 − 145) × 10 m²
    assert items[0].similar_lpu.code == "DRY-001"
    assert (
        items[0].reference_price is None
    )  # continua Não LPU: a tabela não vira preço de referência
    assert items[0].amount_at_issue == 550.0


def test_similar_within_price_or_other_unit_has_no_amount(cfg, ref):
    _, findings, _ = _flag(cfg, ref, _wall(140.0))
    assert [f.amount_at_issue for f in findings if f.kind == "similar_lpu_item"] == [0]
    _, findings, _ = _flag(cfg, ref, _wall(900.0, unit="un"))
    f = next(f for f in findings if f.kind == "similar_lpu_item")
    assert f.amount_at_issue == 0 and "não comparado" in f.evidence


def test_no_finding_without_similar_for_lpu_items_or_whole_item_findings(cfg, ref):
    kinds = lambda fs: [f.kind for f in fs]  # noqa: E731
    assert "similar_lpu_item" not in kinds(
        _flag(cfg, ref, _wall(200.0), similar="NO_REFERENCE")[1]
    )
    assert "similar_lpu_item" not in kinds(
        _flag(cfg, ref, _wall(200.0), similar="XYZ-999")[1]
    )
    assert "similar_lpu_item" not in kinds(_flag(cfg, ref, _wall(200.0, lpu=True))[1])
    out = _flag(cfg, ref, _wall(200.0), classification="out_of_scope")[1]
    assert "similar_lpu_item" not in kinds(out) and "out_of_scope_item" in kinds(out)


def test_item_with_similar_is_not_unpriced_and_approves_with_caveats(cfg, ref):
    items, findings, _ = _flag(cfg, ref, _wall(140.0))
    st = DocumentStage(cfg, ref, ScoreCalculator(ref.rubric))
    assert st.unpriced_items([], items) == []  # há com o que comparar: o similar
    calc = ScoreCalculator(ref.rubric)
    r = calc.compute(findings)
    assert r.recommendation == Recommendation.APPROVE_WITH_CAVEATS
