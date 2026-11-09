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
