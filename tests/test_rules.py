"""Regras determinísticas (sem API): configuração, régua, planilha, checklist por categoria, valor em questão e integridade."""

import os

import pytest
from openpyxl import load_workbook

from atest.config import build_dynaconf
from atest.domain import Recommendation
from atest.llm_schemas import ItemReview, QuoteReview
from atest.photos import PhotoIndex, PhotoStage
from atest.quote import QuoteStage
from atest.repository import QuoteError, list_tickets, load_ground_truth, load_ticket, read_quote
from atest.score import ScoreCalculator


def aps(ref, *kinds):
    return [ScoreCalculator(ref.rubric).finding(t, "test") for t in kinds]


def stage(cls, cfg, ref, **kwargs):
    """Instancia uma etapa do pipeline com a régua das referências."""
    return cls(cfg, ref, ScoreCalculator(ref.rubric), **kwargs)


def review(quote, lpu: dict[int, str], by_item: dict | None = None) -> QuoteReview:
    by_item = by_item or {}
    items = []
    for i in quote.items:
        extra = by_item.get(i.n, {})
        items.append(
            ItemReview(
                n=i.n,
                classification=extra.get("classification", "compliant"),
                reason="",
                lpu_code=lpu[i.n],
                expected_quantity_max=extra.get("qmax", -1),
                plausible_quantity=extra.get("plausible", True),
                duplicate_of=0,
            )
        )
    return QuoteReview(items=items, notes="")


def test_dynaconf_reads_toml_environment_and_variable(monkeypatch):
    assert build_dynaconf("production").batch.kind == "batch"
    monkeypatch.setenv("ATEST_MODELS__MAIN", "claude-opus-5-5")
    assert build_dynaconf().models.main == "claude-opus-5-5"


def test_deck_examples(ref):
    r = ScoreCalculator(ref.rubric).compute(aps(ref, "out_of_scope_item", "quantity_above_expected", "photo_mismatch", "missing_before_photo"))
    assert (r.grades.quote, r.grades.photos, r.score, r.recommendation) == (50, 50, 60, Recommendation.RETURN_TO_SUPPLIER)
    r = ScoreCalculator(ref.rubric).compute(aps(ref, "unjustified_replacement", "out_of_scope_item", "reused_photo", "missing_after_photo"))
    assert (r.score, r.recommendation) == (34, Recommendation.RETURN_LOCKED)


def test_bands_confidence_and_inconsistencies(ref):
    assert ScoreCalculator(ref.rubric).compute([]).recommendation == Recommendation.APPROVE
    r = ScoreCalculator(ref.rubric).compute(aps(ref, "vague_scope", "unreadable_photo"))
    assert r.recommendation == Recommendation.DETAILED_REVIEW
    r = ScoreCalculator(ref.rubric).compute(aps(ref, "inconsistent_scope", "spreadsheet_mismatch"))
    assert (r.grades.scope, r.grades.quote, r.confidence) == (85, 85, "medium")
    assert ScoreCalculator(ref.rubric).compute(aps(ref, "photo_dated_before")).grades.photos == 85


def test_checklist_unified_by_category(cfg):
    req = lambda *a: [r.id for r in cfg.checklists.requirements(*a)]  # noqa: E731
    assert req("alarm", "corrective", "execution") == ["quote", "equipment_photo", "panel_photo", "certificate"]
    assert req("plumbing", "corrective", "quote") == ["quote", "problem_photo"]
    assert req("metalwork", "corrective", "execution") == ["quote", "service_photo"]  # regra genérica


def test_every_ticket_has_category_symptom_scope_and_spreadsheet(cfg):
    for p in list_tickets(cfg.tickets_dir):
        ch = load_ticket(p)
        quote = read_quote(ch.spreadsheets[0].path)
        assert ch.data.category and ch.data.symptom and ch.data.requested_scope
        assert quote.scope == ch.data.requested_scope


def test_nonstandard_spreadsheet(cfg, tmp_path):
    wb = load_workbook(load_ticket(cfg.tickets_dir / "00534519").spreadsheets[0].path)
    del wb["Itens"].tables["tbItens"]
    wb.save(tmp_path / "bad.xlsx")
    with pytest.raises(QuoteError, match="tbItens"):
        read_quote(tmp_path / "bad.xlsx")


def test_amount_at_issue_counts_only_excess(cfg, ref):
    ch = load_ticket(cfg.tickets_dir / "00482193")
    quote = read_quote(ch.spreadsheets[0].path)
    conf = review(
        quote, {1: "PIN-001", 2: "PIN-002", 3: "PIN-003", 4: "PIN-004"}, {3: {"classification": "out_of_scope"}, 4: {"qmax": 240, "plausible": False}}
    )
    quote_stage = stage(QuoteStage, cfg, ref)
    items, _, _ = quote_stage.flag(ch, quote, conf)
    assert [i.amount_at_issue for i in items] == [0, 0, 3150.0, 232.5]  # fachada inteira; massa só 80 m² excedentes

    ch = load_ticket(cfg.tickets_dir / "00534519")
    quote = read_quote(ch.spreadsheets[0].path)
    items, a, _ = quote_stage.flag(ch, quote, review(quote, {1: "ELE-004", 2: "ELE-005", 3: "ELE-006", 4: "ELE-007", 5: "ELE-004"}))
    assert sorted(x.kind for x in a) == ["duplicate_item", "price_above_reference"]
    assert sum(i.amount_at_issue for i in items) == 168 + 16  # duplicado inteiro + R$ 16 acima da LPU no disjuntor


def test_spreadsheet_mismatch_becomes_finding(cfg, ref):
    ch = load_ticket(cfg.tickets_dir / "00540277")
    quote = read_quote(ch.spreadsheets[0].path)
    _, a, _ = stage(QuoteStage, cfg, ref).flag(ch, quote, review(quote, {1: "ELE-008", 2: "ELE-009"}))
    assert [x.kind for x in a] == ["spreadsheet_mismatch"] and "categoria" in a[0].evidence.lower()


def test_integrity_reuse_and_date(cfg, ref, demo):
    photo_stage = stage(PhotoStage, cfg, ref, index=PhotoIndex.from_folders(cfg.history_dir, cfg.tickets_dir))
    for p in list_tickets(cfg.tickets_dir, demo):
        ch = load_ticket(p)
        gt = load_ground_truth(cfg.ground_truth_dir, ch.id)
        photos = [x for x in ch.attachments if x.is_image and not gt.attachments[x.name]["category"].endswith("_doc")]  # documentos não entram
        _, a = photo_stage.integrity(ch, photos)
        expected = ["photo_dated_before", "reused_photo", "reused_photo"] if ch.id == "00517706" else []
        assert sorted(x.kind for x in a) == expected, ch.id


def test_secret_api_key_does_not_leak_into_settings(cfg):
    assert "anthropic_api_key" not in cfg.model_dump()
    assert os.environ.get("ATEST_ANTHROPIC_API_KEY") is None


def test_absorbed_finding_stays_as_evidence_without_discount(ref):
    """missing_after_photo absorve photo_mismatch: o mesmo problema não desconta duas vezes."""
    calc = ScoreCalculator(ref.rubric)
    both = aps(ref, "photo_mismatch", "missing_after_photo")
    assert calc.compute(both).grades.photos == 65  # sem a absorção seriam 30
    assert calc.compute(aps(ref, "photo_mismatch")).grades.photos == 65
    marked = calc.mark_absorbed(both)
    assert [f.absorbed_by for f in marked] == ["missing_after_photo", ""]
    assert calc.compute(marked).score == calc.compute(both).score  # marcar não muda a conta


def test_after_photo_with_unconfirmed_location_reduces_confidence(cfg, ref):
    from atest.domain import Match
    from atest.llm_schemas import PhotoAnalysis, ScopeReading

    ticket = load_ticket(cfg.tickets_dir / "00482193")
    scope = ScopeReading(
        local="",
        environment="",
        equipment="",
        requested_services=[],
        mentioned_quantities=[],
        acceptance_criteria=[],
        expected_evidence=[],
        before_evidence_applicable=False,
        consistent_with_category_symptom=True,
        coherence_note="",
        vague_scope=False,
        vague_reason="",
    )
    photo_stage = stage(PhotoStage, cfg, ref)

    def kinds(done: Match) -> list[str]:
        analysis = PhotoAnalysis(photos=[], has_before_photo=True, done_justification="", done_service=done, items_without_photo=[], notes="")
        return [f.kind for f in photo_stage.flag(ticket, scope, analysis, [])]

    assert kinds(Match.YES) == []
    assert kinds(Match.NO) == ["missing_after_photo"]
    assert kinds(Match.PARTIAL) == kinds(Match.UNDETERMINED) == ["after_photo_unconfirmed_location"]
    r = ScoreCalculator(ref.rubric).compute(aps(ref, "after_photo_unconfirmed_location"))
    assert (r.grades.photos, r.confidence) == (85, "medium")


def test_every_scenario_type_has_a_ticket_in_the_catalog(cfg, ref):
    """Garantia de cobertura: cada tipo de cenário (atest/scenarios.py) tem pelo menos um chamado no catálogo 0300…,
    e o gabarito dele traz o cenário esperado."""
    from atest.scenarios import TAGS, tags_for

    found: dict[str, list[str]] = {t.id: [] for t in TAGS}
    for p in list_tickets(cfg.tickets_dir):
        gt = load_ground_truth(cfg.ground_truth_dir, p.name)
        if gt and gt.scenario:
            for tag in tags_for(gt, ref.rubric):
                found[tag].append(p.name)
    assert found["clean"], "catálogo de cenários vazio: rode generator/build_scenarios_dataset.py"
    assert not [t for t, ids in found.items() if not ids]


def test_scenario_tags_from_ground_truth(cfg, ref):
    from atest.scenarios import tags_for

    gt = load_ground_truth(cfg.ground_truth_dir, "00482193").model_copy(
        update={"findings": ["vague_scope", "out_of_scope_item", "price_above_reference", "photo_mismatch"], "checklist_ok": True}
    )
    tags = tags_for(gt, ref.rubric)
    assert {"scope_bad", "scope_vague", "quote_multiple", "quote_out_of_scope", "quote_price", "photo_mismatch", "multi_validation"} <= set(tags)
    assert "clean" not in tags and tags_for(None, ref.rubric) == []


def test_low_confidence_reason_is_in_portuguese(ref):
    """O motivo da análise detalhada cita os redutores pelo nome em português, não pela chave interna."""
    calc = ScoreCalculator(ref.rubric)
    r = calc.compute(aps(ref, "vague_scope", "after_photo_unconfirmed_location"), ["unreadable_quote"])
    assert r.recommendation == Recommendation.DETAILED_REVIEW
    assert r.confidence_reducers == ["after_photo_unconfirmed_location", "unreadable_quote", "vague_scope"]  # dados seguem com a chave
    assert "_" not in r.recommendation_reason
    assert "escopo vago" in r.recommendation_reason and "orçamento não lido" in r.recommendation_reason


def test_unverifiable_quantity_is_not_above_expected(cfg, ref):
    """Modelo sem como estimar a quantidade (-1) vira "quantidade não verificável", com o item inteiro em questão."""
    ch = load_ticket(cfg.tickets_dir / "00482193")
    quote = read_quote(ch.spreadsheets[0].path)
    conf = review(quote, {1: "PIN-001", 2: "PIN-002", 3: "PIN-003", 4: "PIN-004"}, {1: {"plausible": False}, 4: {"qmax": 240, "plausible": False}})
    items, a, _ = stage(QuoteStage, cfg, ref).flag(ch, quote, conf)
    by_kind = {f.kind: f for f in a}
    assert set(by_kind) == {"unverifiable_quantity", "quantity_above_expected"}
    assert by_kind["unverifiable_quantity"].reference.startswith("item 1") and by_kind["unverifiable_quantity"].reduces_confidence
    assert items[0].amount_at_issue == items[0].total_value and items[3].amount_at_issue == 232.5


def test_items_without_photo_become_one_finding(cfg, ref):
    from atest.domain import EvaluatedItem, Match
    from atest.llm_schemas import PhotoAnalysis

    ticket = load_ticket(cfg.tickets_dir / "00482193")
    scope = _scope_reading()
    items = [
        EvaluatedItem(n=n, description=d, unit="un", quantity=6, unit_value=10, total_value=60, classification="compliant", reason="", lpu_code="X")
        for n, d in ((1, "Limpeza"), (2, "Higienização"), (3, "Pressões"))
    ]
    photo_stage = stage(PhotoStage, cfg, ref)

    def flag(done: Match, missing: list[int]):
        analysis = PhotoAnalysis(photos=[], has_before_photo=True, done_justification="", done_service=done, items_without_photo=missing, notes="")
        return photo_stage.flag(ticket, scope, analysis, [], items)

    found = [f for f in flag(Match.YES, [2, 3]) if f.kind == "item_without_photo"]
    assert len(found) == 1 and found[0].reference == "itens 2, 3" and "Higienização" in found[0].evidence
    assert [f.kind for f in flag(Match.YES, [])] == []
    assert [f.kind for f in flag(Match.NO, [2])] == ["missing_after_photo"]  # sem prova nenhuma, não pune de novo


def test_relevant_amount_at_issue_threshold(ref):
    calc = ScoreCalculator(ref.rubric)
    limit = ref.rubric.relevant_amount_at_issue_pct
    assert calc.materiality_findings(limit - 0.1) == []
    found = calc.materiality_findings(limit, total=1000, amount=limit * 10)
    assert [f.kind for f in found] == ["relevant_amount_at_issue"] and found[0].validation == "quote"


def test_vague_scope_case_scores_lower(ref):
    """Caso do 03000004: escopo vago, quantidades não verificáveis (100% em questão), local não confirmado, itens sem foto."""
    calc = ScoreCalculator(ref.rubric)
    findings = aps(ref, "vague_scope", "unverifiable_quantity", "after_photo_unconfirmed_location", "item_without_photo")
    r = calc.compute(findings + calc.materiality_findings(100.0))
    assert (r.grades.scope, r.grades.quote, r.grades.photos, r.score) == (65, 70, 70, 69)
    assert r.recommendation == Recommendation.DETAILED_REVIEW


def test_pt_validation_error_and_error_message():
    from pydantic import BaseModel, ValidationError

    from atest.formatting import error_message, pt_validation_error

    class M(BaseModel):
        quantity: float
        name: str

    try:
        M.model_validate({"quantity": "abc"})
    except ValidationError as e:
        text = pt_validation_error(e.errors())
    assert text == "quantity: número inválido; name: campo obrigatório"
    assert error_message(RuntimeError("[quote_review] resposta sem JSON válido")) == "Falha em Orçamento × escopo: resposta sem JSON válido"
    assert error_message(RuntimeError("caiu")) == "Falha na análise: caiu"


def _scope_reading(vague: bool = False):
    from atest.llm_schemas import ScopeReading

    return ScopeReading(
        local="",
        environment="",
        equipment="",
        requested_services=[],
        mentioned_quantities=[],
        acceptance_criteria=[],
        expected_evidence=[],
        before_evidence_applicable=False,
        consistent_with_category_symptom=True,
        coherence_note="",
        vague_scope=vague,
        vague_reason="",
    )
