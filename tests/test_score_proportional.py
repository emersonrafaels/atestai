"""Score proporcional ao que o fornecedor enviou e devolução quando falta o que é pertinente (régua v9)."""

from atest.analysis import AnalysisContext
from atest.domain import EvaluatedItem, Match, Recommendation, Severity
from atest.llm_schemas import AnalyzedPhoto, PhotoAnalysis, QuoteReview
from atest.repository import load_ticket, read_ticket_quote
from atest.score import Measures, ScoreCalculator
from atest.scoring import ScoringStage


def _calc(ref) -> ScoreCalculator:
    return ScoreCalculator(ref.rubric)


def _photos(calc: ScoreCalculator, bad: int, total: int) -> int:
    """Desconto de `bad` fotos fora do escopo em `total` analisadas."""
    fs = [calc.finding("photo_mismatch", "outro ambiente", f"foto{i}.jpg") for i in range(bad)]
    return calc.proportional(fs, Measures(photos=total))[0].discount


def test_more_good_photos_dilute_a_bad_one(ref):
    calc, high = _calc(ref), ref.rubric.discount_by_severity[Severity.HIGH]
    one_of_six, all_six, one_of_one = _photos(calc, 1, 6), _photos(calc, 6, 6), _photos(calc, 1, 1)
    assert one_of_six < _photos(calc, 3, 6) < all_six == one_of_one == high
    assert one_of_six == round(high * (0.5 + 0.5 / 6))  # o piso garante que ainda pesa
    f = calc.proportional([calc.finding("photo_mismatch", "", "a.jpg")], Measures(photos=6))[0]
    assert f.extent_label == "1 de 6 fotos" and f.extent == round(1 / 6, 3)


def test_value_discount_grows_with_the_share_of_the_quote(ref):
    calc = _calc(ref)

    def disc(amount: float) -> int:
        return calc.proportional([calc.finding("price_above_reference", "", "item 1", amount)], Measures(total_value=10_000))[0].discount

    assert disc(20) < disc(2_500) < disc(10_000) == ref.rubric.discount_by_severity[Severity.MEDIUM]
    # sem medidas (gabarito): severidade inteira
    assert calc.proportional([calc.finding("price_above_reference", "", "item 1", 20)], None)[0].discount == 15


def test_same_type_discounts_once_with_the_combined_share(ref):
    calc = _calc(ref)
    fs = [calc.finding("quantity_above_photos", "", f"item {n}", 250) for n in (1, 2)]
    out = calc.proportional(fs, Measures(total_value=1_000))
    assert {f.discount for f in out} == {round(15 * (0.5 + 0.5 * 0.5))} and out[0].extent == 0.5
    assert calc.compute(out).grades.quote == 100 - out[0].discount


def test_requested_service_without_item_returns_to_supplier(ref):
    calc = _calc(ref)
    gap = calc.proportional([calc.finding("scope_not_quoted", "fiação e ENGIE sem item")], Measures(services=3, services_missing=2))
    assert gap[0].discount == round(60 * (0.5 + 0.5 * 2 / 3)) and gap[0].extent_label == "2 sem item de 3 serviços pedidos"
    r = calc.compute(gap)
    assert r.recommendation == Recommendation.RETURN_TO_SUPPLIER and r.recommendation_reason.startswith("O fornecedor precisa ajustar")
    assert r.confidence.value == "high"  # falta do fornecedor não é incerteza da entrada
    # nem a nota alta salva: o pedido não foi tratado
    assert calc.compute(calc.proportional(gap, Measures(services=10, services_missing=1))).recommendation == Recommendation.RETURN_TO_SUPPLIER


def test_amount_at_issue_returns_from_30_percent(ref):
    calc = _calc(ref)
    assert calc.compute([], amount_at_issue_pct=20).recommendation == Recommendation.APPROVE_WITH_CAVEATS
    r = calc.compute([], amount_at_issue_pct=30)
    assert r.recommendation == Recommendation.RETURN_TO_SUPPLIER and "30% do orçamento" in r.recommendation_reason


def test_locks_and_low_confidence_still_rule(ref):
    calc = _calc(ref)
    locked = calc.compute([calc.finding("reused_photo", "", "a.jpg"), calc.finding("scope_not_quoted", "")])
    assert locked.recommendation == Recommendation.RETURN_LOCKED
    vague = calc.compute([calc.finding("vague_scope", ""), calc.finding("unreadable_photo", "", "a.jpg")], amount_at_issue_pct=40)
    assert vague.recommendation == Recommendation.DETAILED_REVIEW  # sem entrada suficiente, nem o valor em questão conclui
    clean = calc.compute([])
    assert (clean.score, clean.recommendation) == (100, Recommendation.APPROVE)


# ------------------------------------------------------------------ calibração com os chamados reais
def _ctx(cfg, ticket: str, amounts: dict[int, tuple[str, float]], photos: int = 0) -> AnalysisContext:
    """Contexto como o pipeline deixa antes do score: itens do orçamento real com os apontamentos gravados."""
    ch = load_ticket(cfg.tickets_dir / ticket)
    calc = ScoreCalculator(cfg.rubric)
    ctx = AnalysisContext(ticket=ch, session=None)
    for i in read_ticket_quote(ch).items:
        item = EvaluatedItem(**i.model_dump(), classification="compliant", reason="", lpu_code="NO_REFERENCE")
        if i.n in amounts:
            kind, amount = amounts[i.n]
            f = calc.finding(kind, "gravado", f"item {i.n}: {i.description}", amount)
            item.findings, item.amount_at_issue = [f], amount
            ctx.findings.append(f)
        ctx.items.append(item)
    if photos:
        reading = AnalyzedPhoto(index=0, environment="", what_it_shows="", moment="before", readable=True, matches_scope=Match.YES,
                                reason="", covered_items=[])
        ctx.photo_analysis = PhotoAnalysis(photos=[reading.model_copy(update={"index": k}) for k in range(photos)],
                                           has_before_photo=True, done_justification="", done_service=Match.UNDETERMINED,
                                           items_without_photo=[], quantity_checks=[], notes="")
    return ctx


def test_04159084_acrylic_sheet_without_the_wiring_is_returned(cfg, ref):
    """Só a chapa de acrílico: a fiação e a desativação da ENGIE, pedidas, ficaram sem item; preço 38% acima do anúncio."""
    ctx = _ctx(cfg, "04159084", {1: ("price_above_market", 114.54)}, photos=1)
    ctx.findings.append(ScoreCalculator(cfg.rubric).finding("scope_not_quoted", "fiação e ENGIE sem item"))
    ctx.service_coverage = QuoteReview(items=[], notes="", service_coverage=[
        {"n": 1, "service": "Organizar a fiação do quadro", "items": [], "covered": "no", "note": ""},
        {"n": 2, "service": "Instalar chapa de acrílico", "items": [1], "covered": "yes", "note": ""},
        {"n": 3, "service": "Desativar a medição da ENGIE", "items": [], "covered": "no", "note": ""},
    ]).service_coverage
    ScoringStage(cfg, ref, ScoreCalculator(cfg.rubric)).run(ctx)
    s = ctx.score
    assert s.recommendation == Recommendation.RETURN_TO_SUPPLIER and "serviço pedido no chamado sem item" in s.recommendation_reason
    assert s.grades.scope == 100 - round(60 * (0.5 + 0.5 * 2 / 3)) and s.grades.quote <= 100 - round(ctx.amount_at_issue_pct)
    assert s.score < 85 and s.confidence.value == "high"


def test_04164650_half_of_the_floor_quote_in_question_is_returned(cfg, ref):
    """Quantidades acima das fotos em 4 itens: metade do orçamento em questão."""
    amounts = {1: 59.66, 2: 625.44, 3: 91.14, 4: 37.70}
    ctx = _ctx(cfg, "04164650", {n: ("quantity_above_photos", v) for n, v in amounts.items()}, photos=6)
    ScoringStage(cfg, ref, ScoreCalculator(cfg.rubric)).run(ctx)
    s = ctx.score
    assert round(ctx.amount_at_issue_pct) == 50
    assert s.grades.quote == 50  # teto: a nota acompanha a parte do orçamento sem questionamento
    assert s.recommendation == Recommendation.RETURN_TO_SUPPLIER and "50% do orçamento" in s.recommendation_reason
