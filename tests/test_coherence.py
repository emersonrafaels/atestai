"""Etapa "Categoria e solução": causa especial (vandalismo, desastre natural) × categoria/sintoma e solução × problema."""

from types import SimpleNamespace

import pytest

from atest.coherence import CoherenceStage
from atest.domain import EvaluatedDocument, Match, ReportAnswer
from atest.llm_schemas import CoherenceReview
from atest.providers import ProviderError
from atest.score import ScoreCalculator


def review(**kw) -> CoherenceReview:
    base = dict(
        reported_problem="câmera sem imagem",
        cause="wear_or_failure",
        cause_evidence="",
        category_fits=True,
        symptom_fits=True,
        suggested_category="",
        suggested_symptom="",
        classification_note="",
        solution="troca da fonte",
        solution_coherent="yes",
        solution_note="",
    )
    return CoherenceReview(**{**base, **kw})


def code(value: str, label: str):
    return SimpleNamespace(value=value, label=label)


@pytest.fixture
def stage(cfg, ref):
    return CoherenceStage(cfg, ref, ScoreCalculator(ref.rubric))


CCTV, NO_IMAGE, VANDALISM = (
    code("cctv", "Cftv"),
    code("no_image", "Sem imagem"),
    code("vandalismo", "Vandalismo"),
)


def kinds(fs):
    return [f.kind for f in fs]


def test_ticket_cause_comes_from_category_or_symptom(ref):
    assert ref.rubric.cause_of("cctv", "vandalismo") == "vandalism"
    assert ref.rubric.cause_of("civil", "desastre_natural") == "natural_disaster"
    assert ref.rubric.cause_of("cctv", "no_image") == ""


def test_vandalism_opened_as_common_failure(stage):
    fs = stage.findings(
        review(
            cause="vandalism",
            cause_evidence="lente quebrada por impacto (foto 2)",
            symptom_fits=False,
            suggested_symptom="vandalismo",
        ),
        CCTV,
        NO_IMAGE,
        "",
    )
    assert kinds(fs) == ["cause_miscategorized"]
    f = fs[0]
    assert f.review and f.severity == "high"
    assert (
        "indicam vandalismo (lente quebrada" in f.evidence
        and "Cftv / Sem imagem" in f.evidence
    )
    assert "o correto seria Vandalismo" in f.evidence


def test_opened_as_vandalism_but_evidence_shows_wear(stage):
    fs = stage.findings(
        review(cause="wear_or_failure", cause_evidence="ferrugem na carcaça"),
        CCTV,
        VANDALISM,
        "vandalism",
    )
    assert kinds(fs) == ["cause_miscategorized"]
    assert "aberto como vandalismo" in fs[0].evidence and "desgaste" in fs[0].evidence


def test_natural_disaster_opened_as_vandalism_is_also_wrong(stage):
    fs = stage.findings(review(cause="natural_disaster"), CCTV, VANDALISM, "vandalism")
    assert kinds(fs) == ["cause_miscategorized"]


def test_undetermined_cause_does_not_accuse(stage):
    """Sem evidência da causa, aberto como vandalismo não é apontado (nem presumido)."""
    assert (
        stage.findings(review(cause="undetermined"), CCTV, VANDALISM, "vandalism") == []
    )
    assert stage.findings(review(cause="vandalism"), CCTV, VANDALISM, "vandalism") == []


def test_common_miscategorization(stage):
    fs = stage.findings(
        review(
            category_fits=False,
            suggested_category="alarm",
            classification_note="É a central de alarme, não CFTV",
        ),
        CCTV,
        NO_IMAGE,
        "",
    )
    assert kinds(fs) == ["miscategorized_ticket"]
    assert fs[0].caveats and "o correto seria Alarme" in fs[0].evidence


def test_solution_coherence(stage):
    no = stage.findings(
        review(
            solution_coherent="no",
            solution_note="troca lâmpadas para disjuntor desarmando",
        ),
        CCTV,
        NO_IMAGE,
        "",
    )
    assert kinds(no) == ["solution_incoherent"] and no[0].returns
    partial = stage.findings(review(solution_coherent="partial"), CCTV, NO_IMAGE, "")
    assert kinds(partial) == ["solution_partially_coherent"] and partial[0].caveats
    assert (
        stage.findings(review(solution_coherent="undetermined"), CCTV, NO_IMAGE, "")
        == []
    )


def test_clean_keeps_only_catalog_codes(stage):
    r = stage.clean(
        review(suggested_category="Inventada", suggested_symptom="Vandalismo"),
        "SISR",
        "cctv",
    )
    assert r.suggested_category == "" and r.suggested_symptom == "vandalismo"
    same = stage.clean(review(suggested_category="cctv"), "SISR", "cctv")
    assert same.suggested_category == ""  # sugerir a mesma categoria não é sugestão


def test_cause_absorbs_text_only_inconsistency(ref):
    """inconsistent_scope (só o texto) e cause_miscategorized (todas as evidências) são o mesmo problema: desconta uma vez."""
    scorer = ScoreCalculator(ref.rubric)
    marked = scorer.mark_absorbed(
        [
            scorer.finding("inconsistent_scope", "x", "escopo"),
            scorer.finding("cause_miscategorized", "y", "Cftv"),
        ]
    )
    by = {f.kind: f.absorbed_by for f in marked}
    assert (
        by["inconsistent_scope"] == "cause_miscategorized"
        and by["cause_miscategorized"] == ""
    )


class Session:
    def __init__(self, answer=None, fail=False):
        self.answer, self.fail, self.calls = answer, fail, []

    def ask(self, task, parts, output, **kw):
        self.calls.append((task, parts[0].text, kw))
        if self.fail:
            raise ProviderError("resposta inválida")
        return self.answer


def context(cfg, session, symptom="no_image"):
    from atest.analysis import AnalysisContext
    from atest.domain import Ticket

    ticket = Ticket.model_validate(
        {
            "ticket_id": "04175640",
            "workstream": "SISR",
            "maintenance_type": "corrective",
            "category": "cctv",
            "symptom": symptom,
            "requested_scope": "Câmera 05 externa sem imagem",
            "branch": {
                "code": "5590",
                "name": "Niterói Icaraí",
                "environment": "area_externa",
            },
            "supplier": {"name": "Fornecedor", "cnpj": "00.000.000/0001-00"},
            "dates": {"opening": "2026-11-01", "supplier_submission": "2026-11-05"},
        }
    )
    ctx = AnalysisContext(
        ticket=SimpleNamespace(data=ticket, id="04175640"), session=session
    )
    ctx.documents = [
        EvaluatedDocument(
            file="Relatorio.pdf",
            kind="technical_report",
            legible=Match.YES,
            matches_ticket=Match.YES,
            answers=[
                ReportAnswer(question="O equipamento estava vandalizado?", answer="yes")
            ],
        )
    ]
    return ctx


def test_run_sends_evidence_and_catalog(cfg, stage):
    s = Session(review(cause="vandalism", symptom_fits=False))
    ctx = context(cfg, s)
    stage.run(ctx)
    task, text, kw = s.calls[0]
    assert task == "coherence" and kw["meta"] == {"ticket_cause": ""}
    assert (
        "O equipamento estava vandalizado? → Sim" in text
    )  # resposta do relatório em PDF
    assert "- vandalismo: Vandalismo" in text  # sintoma de causa especial na lista
    assert (
        "- alarm: Alarme" in text and "- civil: Civil" not in text
    )  # só as categorias da esteira
    assert "FOTOS: não analisadas" in text
    assert kinds(ctx.findings) == ["cause_miscategorized"] and ctx.coherence is not None


def test_run_without_model_answer_reduces_confidence(cfg, stage):
    ctx = context(cfg, Session(fail=True))
    stage.run(ctx)
    assert ctx.findings == [] and ctx.coherence is None
    assert ctx.confidence_reducers == ["coherence_not_checked"]
