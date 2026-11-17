"""Agência por nome e/ou código e comparação com chamados da mesma agência (possível duplicidade)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from atest.analysis import AnalysisContext
from atest.api import create_app
from atest.domain import Branch, Recommendation, Ticket
from atest.llm_schemas import RelatedTicketsReview
from atest.related import PoolEntry, RelatedTicketsStage, find_candidates
from atest.repository import LoadedTicket
from atest.score import ScoreCalculator


# ============================================================================ agência
def test_branch_accepts_name_code_or_both():
    assert Branch(code="418").code == "0418"
    assert Branch(code=" 0.418 ", name="  Ag.  Centro ").name == "Ag. Centro"
    assert Branch(code=7).code == "0007"
    assert Branch(name="Ag. Centro").code == ""
    assert (
        Branch(code="0661", name="Ag. Saúde").label == "Ag. Saúde (núm. do ponto 0661)"
    )
    assert Branch(code="0661").label == "Agência núm. do ponto 0661"
    assert Branch(name="Ag. Saúde").label == "Ag. Saúde"
    for bad in ({"code": "10000"}, {"code": "12a"}, {}, {"code": "", "name": "  "}):
        with pytest.raises(ValidationError):
            Branch(**bad)


def test_same_branch_by_code_then_by_normalized_name():
    assert Branch(code="661", name="x").same_as(Branch(code="0661", name="y"))
    assert not Branch(code="1", name="Centro").same_as(Branch(code="2", name="Centro"))
    assert Branch(name="Itaú Ag. Saúde").same_as(Branch(name="Ag. Saude"))
    assert Branch(name="Ag. Campinas - Cambuí").same_as(
        Branch(code="1520", name="Campinas Cambuí (fictícia)")
    )
    assert not Branch(code="1520").same_as(Branch(name="Campinas Cambuí"))
    assert not Branch(name="Ag. Centro").same_as(Branch(name="Ag. Centro Norte"))


# ============================================================================ candidatos
def _ticket(tid: str, opening: date, branch: dict, **kw) -> Ticket:
    return Ticket(
        ticket_id=tid,
        workstream="SETA",
        maintenance_type="corrective",
        moment="quote",
        category=kw.pop("category", "civil"),
        symptom="forro_danificado",
        requested_scope=kw.pop("scope", "Forro manchado no autoatendimento"),
        branch=branch,
        supplier={"name": "Fornecedor", "cnpj": ""},
        dates={"opening": opening, "supplier_submission": opening + timedelta(days=1)},
        dataset=kw.pop("dataset", "casos"),
        **kw,
    )


def _entry(t: Ticket) -> PoolEntry:
    return PoolEntry(LoadedTicket(data=t, folder=Path("."), attachments=[]), "tickets")


def test_candidates_window_still_open_and_skips(cfg):
    # janela curta fixa, para separar "na janela" de "fora, mas segue aberto"
    rule = cfg.rubric.related_tickets.model_copy(update={"window_days": 5})
    day = date(2026, 11, 10)
    b = {"code": "1520", "name": "Campinas"}
    cur = _ticket("04000001", day, b)
    pool = [
        _entry(cur),
        _entry(_ticket("04000002", day - timedelta(days=5), b)),  # na janela
        _entry(_ticket("04000003", day + timedelta(days=3), b)),  # na janela, depois
        _entry(
            _ticket("04000004", day - timedelta(days=30), b)
        ),  # fora da janela, segue aberto
        _entry(
            _ticket("04000005", day - timedelta(days=30), b, status="approved")
        ),  # encerrado
        _entry(
            _ticket("04000006", day - timedelta(days=6), b, status="closed")
        ),  # encerrado, fora
        _entry(
            _ticket("04000007", day, {"code": "1521", "name": "Campinas"})
        ),  # outra agência
        _entry(_ticket("04000008", day, b, dataset="validation")),  # conjunto fora
        _entry(
            _ticket("04000009", day + timedelta(days=9), b)
        ),  # aberto depois da janela
    ]
    found = find_candidates(cur, [e for e in pool], rule, ["validation"])
    got = {c.data.ticket_id: c.in_window for c in found}
    assert got == {"04000002": True, "04000003": True, "04000004": False}
    no_open = rule.model_copy(update={"include_still_open": False})
    assert {c.data.ticket_id for c in find_candidates(cur, pool, no_open)} == {
        "04000002",
        "04000003",
        "04000008",
    }


def test_default_window_is_60_days(cfg):
    """Padrão da régua: 60 dias; um chamado da agência já encerrado 30 dias antes ainda entra (pagamento em dobro)."""
    rule = cfg.rubric.related_tickets
    assert rule.window_days == 60
    day = date(2026, 11, 10)
    b = {"code": "1520", "name": "Campinas"}
    cur = _ticket("04000001", day, b)
    pool = [
        _entry(cur),
        _entry(_ticket("04000005", day - timedelta(days=30), b, status="paid")),
        _entry(_ticket("04000006", day - timedelta(days=61), b, status="paid")),
    ]
    got = {c.data.ticket_id: c.in_window for c in find_candidates(cur, pool, rule)}
    assert got == {"04000005": True}


# ============================================================================ etapa e régua
class _FakeSession:
    def __init__(self, probabilities: dict[str, int]):
        self.probabilities = probabilities
        self.asked: list[dict] = []

    def ask(self, task, parts, output, **kw):
        self.asked.append({"task": task, "meta": kw.get("meta"), "text": parts[0].text})
        return RelatedTicketsReview(
            judgments=[
                {
                    "ticket_id": tid,
                    "relation": "same_problem" if p >= 70 else "different",
                    "probability": p,
                    "matching_points": ["mesmo forro"] if p >= 70 else [],
                    "differences": [],
                    "reason": "teste",
                }
                for tid, p in self.probabilities.items()
            ]
        )


def test_stage_flags_duplicate_and_lists_related(cfg, ref):
    day = date(2026, 11, 10)
    b = {"code": "1520", "name": "Campinas"}
    cur = _ticket("04000001", day, b)
    pool = [
        _entry(cur),
        _entry(_ticket("04000002", day - timedelta(days=2), b, scope="Goteira no teto dos caixas")),
        _entry(_ticket("04000003", day - timedelta(days=1), b, category="electrical", scope="Tomada queimada")),
        _entry(_ticket("04000004", day - timedelta(days=40), b, scope="Split pingando")),
    ]  # fmt: skip
    stage = RelatedTicketsStage(cfg, ref, ScoreCalculator(ref.rubric), pool=pool)
    session = _FakeSession({"04000002": 88, "04000003": 5, "04000004": 50})
    ctx = AnalysisContext(ticket=pool[0].ticket, session=session)  # type: ignore[arg-type]
    stage.run(ctx)

    assert session.asked[0]["task"] == "related_tickets"
    assert set(session.asked[0]["meta"]["candidates"]) == {
        "04000002",
        "04000003",
        "04000004",
    }
    assert "Goteira no teto dos caixas" in session.asked[0]["text"]
    assert [r.ticket_id for r in ctx.related.tickets] == [
        "04000002",
        "04000004",
        "04000003",
    ]
    assert [r.flagged for r in ctx.related.tickets] == [True, False, False]
    dup = [f for f in ctx.findings if f.kind == "possible_duplicate_ticket"]
    assert len(dup) == 1 and dup[0].reference == "chamado 04000002" and dup[0].review
    # 50% (entre show_probability e min_probability) aparece no racional, sem apontamento
    assert any("04000004" in line for line in ctx.rationale())
    assert not any("04000003" in line for line in ctx.rationale())


def test_stage_skips_synthetic_datasets_and_no_candidates(cfg, ref):
    day = date(2026, 11, 10)
    b = {"code": "1520", "name": "Campinas"}
    synthetic = _ticket("01000001", day, b, dataset="validation")
    stage = RelatedTicketsStage(
        cfg, ref, ScoreCalculator(ref.rubric), pool=[_entry(synthetic)]
    )
    session = _FakeSession({})
    ctx = AnalysisContext(ticket=_entry(synthetic).ticket, session=session)  # type: ignore[arg-type]
    stage.run(ctx)
    assert ctx.related.skipped and not session.asked

    alone = _ticket("04000001", day, b)
    stage = RelatedTicketsStage(
        cfg, ref, ScoreCalculator(ref.rubric), pool=[_entry(alone)]
    )
    ctx = AnalysisContext(ticket=_entry(alone).ticket, session=session)  # type: ignore[arg-type]
    stage.run(ctx)
    assert ctx.related.tickets == [] and not ctx.related.skipped and not session.asked


def test_duplicate_goes_to_detailed_review_but_lock_wins(ref):
    calc = ScoreCalculator(ref.rubric)
    dup = calc.finding("possible_duplicate_ticket", "mesmo forro", "chamado 04000002")
    res = calc.compute([dup])
    assert res.recommendation == Recommendation.DETAILED_REVIEW
    assert "04000002" in res.recommendation_reason
    # antes de devolver ao fornecedor, a pessoa analista confere se o chamado deve seguir
    out = calc.finding("out_of_scope_item", "pintura", "item 3")
    assert calc.compute([dup, out]).recommendation == Recommendation.DETAILED_REVIEW
    reused = calc.finding("reused_photo", "cópia", "IMG_1.jpg")
    assert calc.compute([dup, reused]).recommendation == Recommendation.RETURN_LOCKED


# ============================================================================ envio pelo painel
def test_upload_accepts_branch_name_or_code(cfg):
    c = TestClient(create_app(cfg))
    spreadsheet = next(
        (cfg.tickets_dir / "00534519" / "attachments").glob("*.xlsx")
    ).read_bytes()
    photo = next(
        (cfg.tickets_dir / "00534519" / "attachments").glob("IMG_*.jpg")
    ).read_bytes()
    form = {
        "workstream": "SETA",
        "category": "electrical",
        "symptom": "electrical_failure",
        "maintenance_type": "corrective",
        "moment": "quote",
        "scope": "Trocar tomadas queimadas",
    }

    def send(**branch):
        return c.post(
            "/api/tickets",
            data={**form, **branch},
            files=[
                ("spreadsheet", ("q.xlsx", spreadsheet)),
                ("attachments", ("a.jpg", photo, "image/jpeg")),
            ],
        )

    created = []
    try:
        r = send(branch_code="418")
        assert r.status_code == 201, r.text
        created.append(r.json()["ticket_id"])
        assert (
            r.json()["branch_code"] == "0418"
            and r.json()["branch"] == "Agência núm. do ponto 0418"
        )
        r = send(branch_name="Ag. Centro")
        assert r.status_code == 201, r.text
        created.append(r.json()["ticket_id"])
        assert r.json()["branch_code"] == "" and r.json()["branch"] == "Ag. Centro"
        r = send()
        assert r.status_code == 422 and "número do ponto" in r.json()["detail"]
        r = send(branch_code="12345")
        assert r.status_code == 422 and "0 a 9999" in r.json()["detail"]
    finally:
        for tid in created:
            c.delete(f"/api/tickets/{tid}")


def test_last_assessment_lists_flagged_duplicates():
    from atest.api import flagged_related

    raw = '[{"ticket_id": "04174102", "flagged": true}, {"ticket_id": "04172318", "flagged": false}]'
    assert flagged_related(raw) == ["04174102"]
    assert flagged_related(None) == [] and flagged_related("não é json") == []
