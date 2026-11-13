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


def review(quote, lpu: dict[int, str], by_item: dict | None = None, uncovered: list[str] | None = None) -> QuoteReview:
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
    coverage = [{"n": n, "service": s, "items": [], "covered": "no", "note": ""} for n, s in enumerate(uncovered or [], 1)]
    return QuoteReview(items=items, service_coverage=coverage, notes="")


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
    from atest.repository import read_ticket_quote

    for p in list_tickets(cfg.tickets_dir):
        ch = load_ticket(p)
        quote = read_ticket_quote(ch)  # planilha completa (aba Chamado) ou só com os itens
        assert ch.data.category and ch.data.symptom and ch.data.requested_scope
        assert quote.scope == ch.data.requested_scope


def test_nonstandard_spreadsheet(cfg, tmp_path):
    """Sem a Tabela do Excel, os itens são lidos pelas colunas; sem as colunas dos itens, a planilha é recusada."""
    path = load_ticket(cfg.tickets_dir / "00534519").spreadsheets[0].path
    wb = load_workbook(path)
    del wb["Itens"].tables["tbItens"]
    wb.save(tmp_path / "no_table.xlsx")
    assert read_quote(tmp_path / "no_table.xlsx").items == read_quote(path).items
    wb["Itens"]["B1"] = "Serviço"  # sem a coluna Descrição
    wb.save(tmp_path / "bad.xlsx")
    with pytest.raises(QuoteError, match="itens"):
        read_quote(tmp_path / "bad.xlsx")


def test_items_only_spreadsheet_uses_ticket_data(cfg, tmp_path):
    """Planilha só com os itens (sem a aba Chamado): o resto vem do chamado e não há planilha divergente."""
    from openpyxl import Workbook

    from atest.repository import quote_defaults

    ch = load_ticket(cfg.tickets_dir / "00534519")
    wb = Workbook()
    ws = wb.active
    ws.append(["Descrição", "Quantidade", "Valor unitário"])  # sem Item, Unidade e Valor total: são completados
    ws.append(["Tomada 2P+T 10A", 6, 28.0])
    ws.append(["Disjuntor 20A", 1, 64.0])
    wb.save(tmp_path / "itens.xlsx")
    with pytest.raises(QuoteError, match="Chamado"):
        read_quote(tmp_path / "itens.xlsx")  # sem os dados do chamado, a aba Chamado continua obrigatória
    q = read_quote(tmp_path / "itens.xlsx", quote_defaults(ch.data))
    assert [(i.n, i.unit, i.total_value) for i in q.items] == [(1, "un", 168.0), (2, "un", 64.0)]
    assert (q.ticket_id, q.category, q.symptom, q.scope) == (ch.data.ticket_id, ch.data.category, ch.data.symptom, ch.data.requested_scope)


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
        analysis = PhotoAnalysis(
            photos=[], has_before_photo=True, done_justification="", done_service=done, items_without_photo=[], quantity_checks=[], notes=""
        )
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
        analysis = PhotoAnalysis(
            photos=[], has_before_photo=True, done_justification="", done_service=done, items_without_photo=missing, quantity_checks=[], notes=""
        )
        return photo_stage.flag(ticket, scope, analysis, [], items)

    found = [f for f in flag(Match.YES, [2, 3]) if f.kind == "item_without_photo"]
    assert len(found) == 1 and found[0].reference == "itens 2, 3" and "Higienização" in found[0].evidence
    assert [f.kind for f in flag(Match.YES, [])] == []
    assert [f.kind for f in flag(Match.NO, [2])] == ["missing_after_photo"]  # sem prova nenhuma, não pune de novo


def test_relevant_amount_at_issue_threshold(ref):
    calc = ScoreCalculator(ref.rubric)
    limit = ref.rubric.relevant_amount_at_issue_pct
    assert calc.materiality_findings([], limit - 0.1) == []
    found = calc.materiality_findings([], limit, total=1000, amount=limit * 10)
    assert [f.kind for f in found] == ["relevant_amount_at_issue"] and found[0].validation == "quote"
    # teto: a nota de Orçamento não passa de 100 − % em questão; desconta só o que falta para chegar lá
    assert found[0].discount == round(limit)
    half = calc.materiality_findings(aps(ref, "quantity_above_photos"), 50.0)
    assert half[0].discount == 35 and calc.compute(aps(ref, "quantity_above_photos") + half).grades.quote == 50
    assert calc.materiality_findings(aps(ref, "out_of_scope_item", "duplicate_item"), 20.0) == []  # já abaixo do teto


def test_vague_scope_case_scores_lower(ref):
    """Caso do 03000004: escopo vago, quantidades não verificáveis (100% em questão), local não confirmado, itens sem foto."""
    calc = ScoreCalculator(ref.rubric)
    findings = aps(ref, "vague_scope", "unverifiable_quantity", "after_photo_unconfirmed_location", "item_without_photo")
    r = calc.compute(findings + calc.materiality_findings(findings, 100.0), amount_at_issue_pct=100.0)
    assert (r.grades.scope, r.grades.quote, r.grades.photos, r.score) == (65, 0, 70, 41)
    # tudo em questão porque o escopo é vago: falta informação para concluir, não é só ajuste do fornecedor
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
    assert error_message(RuntimeError("[quote_review] resposta sem JSON válido")) == "Falha em Orçamento: resposta sem JSON válido"
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


def test_checklist_rule_by_workstream(cfg):
    """Regra só de uma esteira vale só para os chamados dela; a outra esteira segue a regra geral."""
    rules = [r.model_dump() for r in cfg.checklists.rules]
    rules.append({"workstream": "SISR", "category": "*", "maintenance": "*", "moment": "quote",
                  "requirements": [{"id": "quote", "description": "Orçamento", "accepted": ["quote_doc"]}]})
    c = cfg.with_overrides(**{"checklists.rules": rules}).checklists
    req = lambda *a: [r.id for r in c.requirements(*a)]  # noqa: E731
    assert req("plumbing", "corrective", "quote", "SISR") == ["quote"]
    assert req("plumbing", "corrective", "quote", "SETA") == ["quote", "problem_photo"]


def test_rubric_adjusted_by_workstream(cfg):
    """Ajuste por esteira: desativar ou trocar a severidade só na esteira; a outra segue o padrão."""
    rub = cfg.rubric.model_dump(mode="json")
    rub["finding_types"]["vague_scope"]["by_workstream"] = {"SISR": {"enabled": False}, "SETA": {"severity": "low"}}
    r = cfg.with_overrides(**{"rubric": rub}).rubric
    assert r.for_workstream("SISR").finding_types["vague_scope"].enabled is False
    assert r.for_workstream("SETA").finding_types["vague_scope"].severity == "low"
    assert r.finding_types["vague_scope"].enabled and r.finding_types["vague_scope"].severity == cfg.rubric.finding_types["vague_scope"].severity


def test_documents_ocr_findings(cfg, ref):
    """Leitura de documentos: datas, documento de outro chamado, ilegível e preço de mercado abaixo do cobrado."""
    from datetime import date

    from atest.documents import DocumentStage, parse_date
    from atest.domain import DocumentPrice, EvaluatedDocument, Match

    assert parse_date("Data do atendimento: 20/10/2026") == date(2026, 10, 20)
    assert parse_date("20/10/26") == date(2026, 10, 20) and parse_date("sem data") is None

    ch = load_ticket(cfg.tickets_dir / "04159084")
    quote_stage = stage(QuoteStage, cfg, ref)
    from atest.repository import read_ticket_quote

    quote = read_ticket_quote(ch)
    items, _, _ = quote_stage.flag(ch, quote, review(quote, {1: ""}))
    doc_stage = stage(DocumentStage, cfg, ref)

    def doc(**kw) -> EvaluatedDocument:
        return EvaluatedDocument(**{"file": "x.jpg", "legible": Match.YES, "matches_ticket": Match.YES, **kw})

    ok = doc(service_date="20/10/2026")
    assert doc_stage.flag(ch, [ok]) == []
    bad = [doc(service_date="01/09/2026"), doc(matches_ticket=Match.NO, divergences=["outra agência"]), doc(legible=Match.NO)]
    kinds = [f.kind for f in doc_stage.flag(ch, bad)]
    assert kinds == ["document_date_inconsistent", "document_mismatch", "unreadable_document"]

    # print do anúncio: chapa de acrílico a R$ 303,25 contra R$ 417,79 cobrados (38% acima, tolerância 10%)
    ad = doc(kind="price_reference", prices=[DocumentPrice(description="Placa acrílico branco", value=303.25, quote_item=1)])
    found = doc_stage.market_prices([ad], items)
    assert [f.kind for f in found] == ["price_above_market"] and found[0].amount_at_issue == round(417.79 - 303.25, 2)
    assert items[0].amount_at_issue == round(417.79 - 303.25, 2)
    assert doc_stage.market_prices([doc(prices=[DocumentPrice(description="x", value=400.0, quote_item=1)])], items) == []  # dentro da tolerância


def test_lpu_column(cfg, ref, tmp_path):
    """Coluna LPU: sem ela (planilhas antigas) ou em branco, o item é da LPU; "Não" tira o item da comparação com a LPU."""
    from openpyxl import Workbook

    from atest.repository import quote_defaults, read_ticket_quote

    old = read_ticket_quote(load_ticket(cfg.tickets_dir / "00534519"))
    assert all(i.lpu for i in old.items)  # planilha antiga, sem a coluna
    ch = load_ticket(cfg.tickets_dir / "04159084")
    new = read_ticket_quote(ch)
    assert [i.lpu for i in new.items] == [False]  # chapa de acrílico, fora da LPU

    wb = Workbook()
    ws = wb.active
    ws.append(["Descrição", "Unidade", "LPU", "Quantidade", "Valor unitário"])
    ws.append(["Tomada 2P+T", "un", "Sim", 2, 30.0])
    ws.append(["Chapa de acrílico", "un", "não", 1, 400.0])
    ws.append(["Disjuntor", "un", None, 1, 60.0])
    ws.append(["Fio 2,5 mm", "m", True, 10, 3.0])  # caixa de seleção do Excel
    wb.save(tmp_path / "lpu.xlsx")
    q = read_quote(tmp_path / "lpu.xlsx", quote_defaults(ch.data))
    assert [i.lpu for i in q.items] == [True, False, True, True]
    ws.append(["Parafuso", "un", "talvez", 4, 1.0])
    wb.save(tmp_path / "bad_lpu.xlsx")
    with pytest.raises(QuoteError, match="LPU"):
        read_quote(tmp_path / "bad_lpu.xlsx", quote_defaults(ch.data))

    # item fora da LPU não é comparado com a tabela, mesmo que o modelo aponte um código parecido
    quote_stage = stage(QuoteStage, cfg, ref)
    _, findings, _ = quote_stage.flag(ch, new, review(new, {1: "ELE-004"}))  # código barato (un): na LPU, daria preço acima
    assert "price_above_reference" not in [f.kind for f in findings]
    as_lpu = new.model_copy(update={"items": [i.model_copy(update={"lpu": True}) for i in new.items]})
    _, findings, _ = quote_stage.flag(ch, as_lpu, review(as_lpu, {1: "ELE-004"}))
    assert "price_above_reference" in [f.kind for f in findings]  # controle: marcado como LPU, a comparação acontece


def test_quantity_above_photos(cfg, ref):
    """Fotos somam ~7 peças quebradas (≈1,42 m²) e o orçamento cobra 4,6 m²: apontamento sobre o excedente; deslocamento fica de fora."""
    from atest.llm_schemas import PhotoAnalysis, QuantityCheck
    from atest.repository import read_ticket_quote

    ch = load_ticket(cfg.tickets_dir / "04164650")
    quote = read_ticket_quote(ch)
    items, _, _ = stage(QuoteStage, cfg, ref).flag(ch, quote, review(quote, {n: "" for n in range(1, 6)}))
    check = dict(what_was_counted="peças quebradas", per_photo="Anexo 2: 1; Anexo 3: 2", count_seen=7, reasoning="peças de 45x45 cm")
    analysis = PhotoAnalysis(
        photos=[], has_before_photo=True, done_justification="", done_service="undetermined", items_without_photo=[], notes="",
        quantity_checks=[
            QuantityCheck(item=1, estimated_quantity=1.42, **check),
            QuantityCheck(item=2, estimated_quantity=1.42, **check),
            QuantityCheck(item=3, estimated_quantity=-1, **check),  # não dá para estimar: não aponta
            QuantityCheck(item=4, estimated_quantity=4.0, **check),  # 4,6 está dentro da tolerância de 25%
        ],
    )
    found = stage(PhotoStage, cfg, ref).quantity_findings(analysis, items)
    assert [f.kind for f in found] == ["quantity_above_photos"] * 2
    assert found[1].amount_at_issue == round((4.6 - 1.42) * 209.88, 2)
    assert items[1].amount_at_issue == found[1].amount_at_issue


def test_plain_language_and_lump_sum_units(cfg, ref):
    """Textos do modelo sem nomes internos de campos; 'un' e 'vb' com quantidade 1 são a mesma cobrança (preço comparado)."""
    from atest.formatting import plain_language, plain_text, same_unit
    from atest.llm_schemas import QuoteReview

    text = "As quantidades não puderam ser confrontadas (expected_quantity_max = -1). O item ficou NO_REFERENCE e compliant."
    assert plain_text(text) == "As quantidades não puderam ser confrontadas. O item ficou sem referência e aderente."
    r = plain_language(QuoteReview(items=[], service_coverage=[], notes="Sem lpu_code para o item 2."))
    assert r.notes == "Sem código da LPU para o item 2."
    assert plain_text("NO_REFERENCE") == "NO_REFERENCE"  # valor de campo (sem espaço) não muda
    assert same_unit("un", "vb", 1) and not same_unit("un", "vb", 2) and same_unit("m²", "M2", 4.6)

    from atest.repository import read_ticket_quote

    ch = load_ticket(cfg.tickets_dir / "04164650")
    quote = read_ticket_quote(ch)
    _, _, notes = stage(QuoteStage, cfg, ref).flag(ch, quote, review(quote, {1: "", 2: "", 3: "", 4: "", 5: "GER-001"}))
    assert not [n for n in notes if "Item 5" in n]  # deslocamento 1 un x GER-001 em vb: comparado, sem nota


def test_scope_not_quoted_and_service_before_approval(cfg, ref):
    """Serviço pedido sem item vira apontamento; 'executado antes da aprovação' só com prova explícita no documento."""
    from atest.documents import DocumentStage
    from atest.domain import EvaluatedDocument, Match
    from atest.repository import read_ticket_quote

    ch = load_ticket(cfg.tickets_dir / "04159084")  # aprovação de orçamento
    quote = read_ticket_quote(ch)
    asked = ["Organizar a fiação emaranhada do quadro", "Desativar a medição da ENGIE"]
    _, findings, _ = stage(QuoteStage, cfg, ref).flag(ch, quote, review(quote, {1: ""}, uncovered=asked))
    gap = [f for f in findings if f.kind == "scope_not_quoted"]
    # falta do fornecedor: devolve (não é incerteza da entrada, então não reduz a confiança)
    assert len(gap) == 1 and "Organizar a fiação" in gap[0].evidence and gap[0].returns and not gap[0].reduces_confidence
    _, findings, _ = stage(QuoteStage, cfg, ref).flag(ch, quote, review(quote, {1: ""}))
    assert "scope_not_quoted" not in [f.kind for f in findings]

    docs = stage(DocumentStage, cfg, ref)
    solution = "instalação de chapa de acrílico p/ proteção do quadro"

    def rat(status: Match) -> EvaluatedDocument:
        return EvaluatedDocument(file="rat.jpg", legible=Match.YES, matches_ticket=Match.YES, service_date="20/10/2026",
                                 solution=solution, service_status=status)

    assert [f.kind for f in docs.flag(ch, [rat(Match.YES)])] == ["service_before_approval"]
    assert docs.flag(ch, [rat(Match.UNDETERMINED)]) == []  # "instalação de…" pode ser o que será feito
    assert docs.flag(ch, [rat(Match.NO)]) == []


def test_amount_at_issue_caps_approve_and_market_price_tolerance(cfg, ref):
    """Nota de aprovar com mais de 10% do orçamento em questão vira 'Aprovar com ressalvas'; preço de mercado tem tolerância própria."""
    from atest.documents import DocumentStage
    from atest.domain import DocumentPrice, EvaluatedDocument, Match
    from atest.repository import read_ticket_quote

    calc = ScoreCalculator(ref.rubric)
    assert calc.compute([], amount_at_issue_pct=9).recommendation == Recommendation.APPROVE
    r = calc.compute([], amount_at_issue_pct=27)
    assert r.recommendation == Recommendation.APPROVE_WITH_CAVEATS and "27% do orçamento" in r.recommendation_reason

    ch = load_ticket(cfg.tickets_dir / "04159084")
    quote = read_ticket_quote(ch)
    items, _, _ = stage(QuoteStage, cfg, ref).flag(ch, quote, review(quote, {1: ""}))
    docs = stage(DocumentStage, cfg, ref)

    def ad(value: float, same: Match) -> EvaluatedDocument:
        price = DocumentPrice(description="Placa acrílico", value=value, quote_item=1, same_product=same)
        return EvaluatedDocument(file="ad.png", legible=Match.YES, matches_ticket=Match.PARTIAL, prices=[price])

    assert docs.market_prices([ad(350.0, Match.YES)], items) == []  # 19% acima: dentro dos 25%
    assert docs.market_prices([ad(303.25, Match.NO)], items) == []  # outro produto: não compara
    sure = docs.market_prices([ad(303.25, Match.YES)], items)
    assert len(sure) == 1 and not sure[0].reduces_confidence
    unsure = docs.market_prices([ad(303.25, Match.PARTIAL)], items)
    assert not unsure[0].reduces_confidence and unsure[0].evidence.startswith("Produto não confirmado")
