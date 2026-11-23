"""Ressalvas: preço sem referência para comparar (no máximo "aprovar com ressalvas") e manchete do resumo coerente."""

from atest.documents import DocumentStage
from atest.domain import (
    DocumentPrice,
    EvaluatedDocument,
    EvaluatedItem,
    Match,
    Recommendation,
)
from atest.formatting import align_summary
from atest.score import ScoreCalculator


def _item(n: int, reference: float | None, **kw) -> EvaluatedItem:
    return EvaluatedItem(
        n=n,
        description=f"Serviço {n}",
        unit="vb",
        quantity=1,
        unit_value=210.0,
        total_value=210.0,
        classification=kw.pop("classification", "compliant"),
        reason="",
        lpu_code="NO_REFERENCE" if reference is None else "HID-001",
        reference_price=reference,
        **kw,
    )


def _doc(prices: list[DocumentPrice]) -> EvaluatedDocument:
    return EvaluatedDocument(
        file="anuncio.png",
        legible=Match.YES,
        matches_ticket=Match.PARTIAL,
        prices=prices,
    )


def test_unpriced_item_without_market_price_is_flagged(cfg, ref):
    st = DocumentStage(cfg, ref, ScoreCalculator(ref.rubric))
    items = [_item(1, 180.0), _item(2, None), _item(3, None)]
    # item 3 tem preço de mercado anexado: dá para comparar
    docs = [
        _doc(
            [
                DocumentPrice(
                    description="mangueira",
                    value=200.0,
                    quote_item=3,
                    same_product=Match.YES,
                )
            ]
        )
    ]
    found = st.unpriced_items(docs, items)
    assert [f.reference for f in found] == ["item 2"]
    assert found[0].kind == "price_not_comparable" and found[0].caveats
    assert items[1].findings == found  # anexado ao item (aparece na aba Orçamento)
    # sem documentos, os dois sem LPU entram
    assert [
        f.reference for f in st.unpriced_items([], [_item(2, None), _item(3, None)])
    ] == ["item 2", "item 3"]


def test_item_already_out_of_the_quote_is_not_flagged_again(cfg, ref):
    st = DocumentStage(cfg, ref, ScoreCalculator(ref.rubric))
    out = ScoreCalculator(ref.rubric).finding("out_of_scope_item", "fora", "item 2")
    assert st.unpriced_items([], [_item(2, None, findings=[out])]) == []


def test_caveat_turns_approve_into_approve_with_caveats(ref):
    calc = ScoreCalculator(ref.rubric)
    clean = calc.compute([])
    assert clean.recommendation == Recommendation.APPROVE
    r = calc.compute([calc.finding("price_not_comparable", "sem LPU", "item 3")])
    assert r.score >= 85  # a nota continua de aprovar...
    assert (
        r.recommendation == Recommendation.APPROVE_WITH_CAVEATS
    )  # ...mas com ressalva
    assert "ressalva" in r.recommendation_reason.lower()


def test_summary_lead_follows_the_rubric_recommendation():
    labels = [r.label for r in Recommendation]
    fixed = align_summary(
        "Recomendo aprovar com ressalvas: o escopo está coberto.", "Aprovar", labels
    )
    assert fixed == "Recomendo aprovar: o escopo está coberto."
    same = "Recomendo aprovar com ressalvas: item 3 sem preço."
    assert align_summary(same, "Aprovar com ressalvas", labels) == same
    assert (
        align_summary("O escopo está coberto.", "Aprovar", labels)
        == "O escopo está coberto."
    )
    assert (
        align_summary(
            "Recomendo devolver ao fornecedor: foto reaproveitada.",
            "Devolver por trava de integridade",
            labels,
        )
        == "Recomendo devolver por trava de integridade: foto reaproveitada."
    )
