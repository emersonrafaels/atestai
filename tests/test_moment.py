"""Etapa do chamado: na aprovação do orçamento o serviço ainda não foi feito, então nada de cobrar foto do depois."""

from types import SimpleNamespace

import pytest

from atest.admin import AdminError, validate_section
from atest.analysis import AnalysisContext
from atest.assessment import AssessmentStage, AssessmentWriter
from atest.domain import Match, Moment
from atest.formatting import drop_after_service_requests
from atest.llm_schemas import AnalyzedPhoto, AssessmentText, PhotoAnalysis
from atest.photos import EXECUTION_ONLY, PhotoStage
from atest.repository import load_ticket
from atest.score import ScoreCalculator
from atest.scoring import ScoringStage

QUOTE_TICKET = "04159084"


def _ticket(cfg, moment: Moment):
    """Chamado de exemplo com a etapa pedida (o resto do chamado não importa aqui)."""
    t = load_ticket(cfg.tickets_dir / QUOTE_TICKET)
    t.data = t.data.model_copy(update={"moment": moment})
    return t


def test_summary_tells_what_each_stage_expects(cfg):
    quote = _ticket(cfg, Moment.QUOTE).data.summary_text()
    execution = _ticket(cfg, Moment.EXECUTION).data.summary_text()
    assert "AINDA NÃO FOI FEITO" in quote and "Não se espera nem se cobra foto do depois" in quote
    assert "comprovar o RESULTADO" in execution and "AINDA NÃO FOI FEITO" not in execution


def test_drop_after_service_requests_keeps_quote_points():
    notes = ("Só há foto do antes. Faltam fotos do quadro com a fiação organizada e da chapa de acrílico instalada. "
             "As fotos mostram 7 peças quebradas.")
    assert drop_after_service_requests(notes) == "Só há foto do antes. As fotos mostram 7 peças quebradas."
    keep = "Justificar o preço da chapa frente ao anúncio; esclarecer se o serviço já foi executado ou se será executado."
    msg = keep.replace("; esclarecer", "; enviar fotos do quadro com a chapa instalada; esclarecer")
    assert drop_after_service_requests(msg) == keep
    assert drop_after_service_requests("Enviar fotos do resultado após a execução.") == ""
    assert drop_after_service_requests("Informar a espessura da chapa a ser instalada.") == "Informar a espessura da chapa a ser instalada."


def _photo_analysis() -> PhotoAnalysis:
    photo = AnalyzedPhoto(index=1, environment="interna", what_it_shows="quadro com fios soltos", moment="before", readable=True,
                          matches_scope="yes", reason="", covered_items=[1])
    return PhotoAnalysis(
        photos=[photo], has_before_photo=True, done_service=Match.NO, items_without_photo=[1],
        done_justification="Nenhuma foto mostra a chapa instalada.", quantity_checks=[],
        notes="Faltam fotos do quadro com a chapa instalada. O quadro aparece sem proteção.",
    )


class PhotoSession:
    def __init__(self):
        self.content = None

    def ask(self, task, content, output, max_tokens, meta):
        self.content = content
        return _photo_analysis()


@pytest.fixture()
def stage(cfg, ref):
    return PhotoStage(cfg, ref, ScoreCalculator(ref.rubric))


def test_photo_stage_in_quote_does_not_ask_for_the_after(stage, cfg, monkeypatch):
    monkeypatch.setattr("atest.photos.attachment_parts", lambda a, side: [])
    photos = [SimpleNamespace(index=1, name="f1.jpg", path=None, content_type="image/jpeg", is_image=True)]
    monkeypatch.setattr(PhotoStage, "ticket_photos", staticmethod(lambda t, a: photos))
    monkeypatch.setattr(PhotoStage, "integrity", lambda self, t, p: ({}, []))
    scope = SimpleNamespace(before_evidence_applicable=True)
    monkeypatch.setattr("atest.photos.ScopeStage.describe", staticmethod(lambda s: "(escopo)"))

    session = PhotoSession()
    ctx = AnalysisContext(ticket=_ticket(cfg, Moment.QUOTE), session=session, scope=scope)
    stage.run(ctx)
    assert "AINDA NÃO FOI FEITO" in session.content[0].text  # a etapa vai junto das fotos
    assert not [f for f in ctx.findings if f.kind in EXECUTION_ONLY]
    pa = ctx.photo_analysis
    assert (pa.done_service, pa.done_justification, pa.items_without_photo) == (Match.UNDETERMINED, "", [])
    assert pa.notes == "O quadro aparece sem proteção."

    ctx = AnalysisContext(ticket=_ticket(cfg, Moment.EXECUTION), session=PhotoSession(), scope=scope)
    stage.run(ctx)  # na atestação continua cobrando a prova do serviço
    assert "missing_after_photo" in {f.kind for f in ctx.findings} and ctx.photo_analysis.done_service == Match.NO


def test_score_drops_execution_only_findings_in_quote(cfg, ref):
    scorer = ScoreCalculator(ref.rubric)
    for moment, expected in ((Moment.QUOTE, set()), (Moment.EXECUTION, {"missing_after_photo", "item_without_photo"})):
        ctx = AnalysisContext(ticket=_ticket(cfg, moment), session=None)
        ctx.findings = [scorer.finding("missing_after_photo", "x"), scorer.finding("item_without_photo", "y", "item 1")]
        ScoringStage(cfg, ref, scorer).run(ctx)
        assert {f.kind for f in ctx.findings} & EXECUTION_ONLY == expected


def test_supplier_message_by_stage(cfg, ref):
    result = {"recommendation": "return_to_supplier", "recommendation_reason": "x", "amount_at_issue": 0, "amount_at_issue_pct": 0,
              "findings": [{"kind": "photo_dated_before", "reference": "f1.jpg", "description": "d", "evidence": "e"}]}
    assert "durante a execução" in AssessmentWriter.from_template({**result, "moment": "execution"}).supplier_message
    assert "fotos atuais do problema" in AssessmentWriter.from_template({**result, "moment": "quote"}).supplier_message

    class Writer:
        def ask(self, *a, **k):
            return AssessmentText(summary="Aprovar com ressalvas. Falta foto do serviço concluído.",
                                  supplier_message="Justificar o preço da chapa; enviar foto da chapa instalada.")

    ctx = AnalysisContext(ticket=_ticket(cfg, Moment.QUOTE), session=Writer())
    ctx.score = ScoreCalculator(ref.rubric).compute([], [], 0)
    AssessmentStage(cfg, ref, ScoreCalculator(ref.rubric)).run(ctx)
    assert ctx.text.summary == "Aprovar com ressalvas." and ctx.text.supplier_message == "Justificar o preço da chapa."


def test_quote_checklist_never_requires_after_evidence(cfg):
    chk = cfg.checklists.model_dump(mode="json")
    rule = next(r for r in chk["rules"] if r["moment"] == "quote")
    rule["requirements"].append({"id": "after", "description": "Foto do depois", "accepted": ["room_after_photo"], "enabled": True})
    with pytest.raises(AdminError, match="ainda não foi feito"):
        validate_section("checklists", chk, cfg)
    stored = type(cfg.checklists).model_validate(chk)  # regra antiga, salva antes da checagem
    assert "after" not in [r.id for r in stored.requirements("plumbing", "corrective", "quote")]
    assert "service_photo" in [r.id for r in stored.requirements("plumbing", "corrective", "execution")]
