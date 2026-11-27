"""Relatório em PDF no formato checklist da SISR (pergunta + Sim/Não + foto): fotos extraídas viram anexos de foto."""

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from atest.attachments import attachment_parts
from atest.llm_schemas import AnalyzedPhoto, PhotoAnalysis
from atest.pdf_photos import extract_pdf_photos, manifest_path
from atest.photos import PhotoStage
from atest.providers import TextPart
from atest.repository import load_ticket
from atest.score import ScoreCalculator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))
from pdf_report import Question, render_report  # noqa: E402

pytest.importorskip("pypdf")


def jpeg(color, size=(800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def report() -> bytes:
    return render_report(
        "Relatório de Atendimento Técnico - SISR",
        ["Chamado 04175640", "Agência 4417 - Belo Horizonte Savassi"],
        [
            Question("O equipamento estava vandalizado?", True, jpeg((200, 0, 0))),
            Question(
                "A câmera foi substituída?",
                True,
                jpeg((0, 200, 0)),
                note="Bullet 2MP nova",
            ),
            Question("A imagem aparece no gravador?", False, jpeg((0, 0, 200))),
            Question("Houve necessidade de material extra?", None),  # sem foto
        ],
        footer=["Assinatura do gerente: ________"],
    )


def test_extracts_photos_with_question_and_answer_beside(tmp_path):
    pdf = tmp_path / "relatorio.pdf"
    pdf.write_bytes(report())
    photos = extract_pdf_photos(pdf)
    # 3 fotos; a logo (pequena e repetida em todas as páginas) fica de fora
    assert [(p.path.name, p.page) for p in photos] == [
        ("relatorio_p01_foto01.jpg", 1),
        ("relatorio_p01_foto02.jpg", 1),
        ("relatorio_p02_foto01.jpg", 2),
    ]
    first, second, third = (p.context for p in photos)
    assert "vandalizado" in first and "[X] Sim" in first and "Chamado" not in first
    assert "substituída" in second and "Bullet 2MP nova" in second
    assert "vandalizado" not in second  # o bloco da pergunta anterior não entra
    assert "gravador" in third and "[X] Não" in third
    with Image.open(photos[0].path) as im:
        assert im.size == (800, 600)
    # cache: o manifesto é reaproveitado enquanto o PDF não muda
    data = json.loads(manifest_path(pdf).read_text(encoding="utf-8"))
    assert len(data["photos"]) == 3
    photos[0].path.write_bytes(b"marcado")  # se extraísse de novo, sobrescreveria
    assert extract_pdf_photos(pdf)[0].path.read_bytes() == b"marcado"


def test_pdf_without_photos_or_broken(tmp_path):
    pdf = tmp_path / "termo.pdf"
    pdf.write_bytes(render_report("Termo de conclusão", ["Serviço concluído"], []))
    assert extract_pdf_photos(pdf) == []
    broken = tmp_path / "quebrado.pdf"
    broken.write_bytes(b"%PDF-1.4 isto nao e um pdf")
    assert extract_pdf_photos(broken) == []


def test_load_ticket_adds_pdf_photos_as_attachments(tmp_path):
    folder = tmp_path / "04175640"
    (folder / "attachments").mkdir(parents=True)
    (folder / "attachments" / "relatorio.pdf").write_bytes(report())
    ticket = {
        "ticket_id": "04175640",
        "workstream": "SISR",
        "maintenance_type": "corrective",
        "moment": "execution",
        "category": "cctv",
        "symptom": "no_image",
        "requested_scope": "Câmera 03 do autoatendimento vandalizada, sem imagem.",
        "branch": {"code": "4417", "name": "Savassi", "environment": "saguao"},
        "supplier": {"name": "Sentinela", "cnpj": ""},
        "quoted_value": 100,
        "dates": {"opening": "2026-11-10", "supplier_submission": "2026-11-12"},
        "status": "forwarded_to_backoffice",
        "attachments": [
            {
                "file_name": "relatorio.pdf",
                "content_type": "application/pdf",
                "size_bytes": 1,
                "sent_by": "supplier",
                "data_upload": "2026-11-12",
            }
        ],
    }
    (folder / "ticket.json").write_text(json.dumps(ticket), encoding="utf-8")
    t = load_ticket(folder)
    assert [(a.index, a.name, a.is_image) for a in t.attachments] == [
        (1, "relatorio.pdf", False),
        (2, "relatorio_p01_foto01.jpg", True),
        (3, "relatorio_p01_foto02.jpg", True),
        (4, "relatorio_p02_foto01.jpg", True),
    ]
    photo = t.attachments[1]
    assert (photo.source, photo.page) == ("relatorio.pdf", 1)
    # o rótulo enviado ao modelo diz de onde a foto veio e o que está escrito ao lado
    label = attachment_parts(photo)[0]
    assert isinstance(label, TextPart)
    assert "página 1 do PDF relatorio.pdf" in label.text
    assert "vandalizado" in label.text


def test_photo_contradicting_report_answer_is_flagged(cfg, ref):
    stage = PhotoStage(cfg, ref, ScoreCalculator(ref.rubric))
    photo = SimpleNamespace(
        index=2,
        name="relatorio_p01_foto01.jpg",
        source="relatorio.pdf",
        page=1,
        context="1. Câmera reposicionada para o caixa? Resposta: [X] Sim",
    )
    loose = SimpleNamespace(index=3, name="foto.jpg", source="", page=0, context="")

    def read(index, contradicts):
        return AnalyzedPhoto(
            index=index,
            environment="",
            what_it_shows="câmera",
            moment="after",
            readable=True,
            matches_scope="yes",
            reason="",
            covered_items=[],
            contradicts_report=contradicts,
        )

    analysis = PhotoAnalysis(
        photos=[
            read(2, "A imagem mostra o estacionamento, não o caixa"),
            read(3, "texto ignorado: foto solta"),
        ],
        has_before_photo=True,
        done_justification="",
        done_service="yes",
        items_without_photo=[],
        quantity_checks=[],
        notes="",
    )
    ticket = SimpleNamespace(data=SimpleNamespace(moment="quote"))
    scope = SimpleNamespace(before_evidence_applicable=False)
    found = [
        f
        for f in stage.flag(ticket, scope, analysis, [photo, loose])
        if f.kind == "report_answer_contradicted"
    ]
    assert len(found) == 1  # só a foto que veio do relatório
    assert found[0].reference == "relatorio_p01_foto01.jpg"
    assert "estacionamento" in found[0].evidence and "página 1" in found[0].evidence
    out = stage.evaluated_photos(analysis, [photo, loose], {})
    assert out[0].source == "relatorio.pdf" and "reposicionada" in out[0].context
    assert out[1].source == ""


class FakeModel:
    """Modelo falso que responde por tarefa, para o chamado 04175640 (só orçamento + relatório em PDF)."""

    simulated = True
    via_batch = False

    def __init__(self):
        self.sent: dict[str, list[str]] = {}

    def structured(
        self,
        *,
        task,
        system,
        parts,
        output,
        model,
        max_tokens,
        meta,
        fallback=None,
        timeout_s=None,
    ):
        from datetime import datetime

        from atest.domain import LlmCall

        names = dict(
            zip(meta.get("indices", []), meta.get("attachments", []), strict=False)
        )
        self.sent.setdefault(task, []).extend(names.values())
        texts = " ".join(p.text for p in parts if isinstance(p, TextPart))
        data = {
            "identify_attachments": lambda: {
                "attachments": [
                    {
                        "index": i,
                        "category": (
                            "technical_report_doc"
                            if n.endswith(".pdf")
                            else (
                                "cctv_screen_photo"
                                if n.endswith("p02_foto02.jpg")
                                else "equipment_photo"
                            )
                        ),
                        "moment": "after",
                        "readable": True,
                        "short_description": n,
                    }
                    for i, n in names.items()
                ]
            },
            "scope": lambda: {
                "local": "entrada do autoatendimento",
                "environment": "câmera 05",
                "equipment": "câmera",
                "requested_services": ["substituir a câmera 05"],
                "mentioned_quantities": [],
                "acceptance_criteria": [],
                "expected_evidence": [],
                "before_evidence_applicable": False,
                "consistent_with_category_symptom": True,
                "coherence_note": "",
                "vague_scope": False,
                "vague_reason": "",
            },
            "quote_review": lambda: {
                "items": [
                    {
                        "n": n,
                        "classification": "compliant",
                        "reason": "",
                        "expected_quantity_max": -1,
                        "plausible_quantity": True,
                        "duplicate_of": 0,
                        "lpu_code": "NO_REFERENCE",
                        "similar_lpu_code": "NO_REFERENCE",
                    }
                    for n in range(1, 6)
                ],
                "service_coverage": [
                    {
                        "n": 1,
                        "service": "substituir a câmera 05",
                        "items": [1],
                        "covered": "yes",
                        "note": "",
                    }
                ],
                "notes": "",
            },
            "photos": lambda: {
                "photos": [
                    {
                        "index": i,
                        "environment": "",
                        "what_it_shows": n,
                        "moment": "after",
                        "readable": True,
                        "matches_scope": "yes",
                        "reason": "",
                        "covered_items": [1],
                        "contradicts_report": (
                            "A imagem é de uma câmera interna, do backoffice"
                            if n.endswith("p02_foto02.jpg")
                            else ""
                        ),
                    }
                    for i, n in names.items()
                ],
                "has_before_photo": False,
                "done_justification": "câmera nova instalada",
                "done_service": "yes",
                "items_without_photo": [],
                "quantity_checks": [],
                "notes": "",
            },
            "documents": lambda: {
                "documents": [
                    {
                        "index": i,
                        "kind": "service_report",
                        "handwritten": False,
                        "legible": "yes",
                        "transcription": "",
                        "issuer": "",
                        "service_date": "18/11/2026",
                        "start_time": "",
                        "end_time": "",
                        "branch": "5590",
                        "problem": "",
                        "solution": "",
                        "has_signature": True,
                        "service_status": "yes",
                        "prices": [],
                        "answers": [
                            {
                                "question": "O equipamento estava vandalizado?",
                                "answer": "yes",
                                "note": "",
                                "has_photo": False,
                            }
                        ],
                        "matches_ticket": "yes",
                        "divergences": [],
                        "reason": "",
                    }
                    for i in names
                ],
                "notes": "",
            },
            "related_tickets": lambda: {"judgments": []},
            # câmera vandalizada (pergunta 1 do relatório: Sim), mas o chamado foi aberto como Cftv / Sem imagem
            "coherence": lambda: {
                "reported_problem": "câmera 05 externa vandalizada, sem imagem",
                "cause": "vandalism",
                "cause_evidence": "relatório: o equipamento estava vandalizado? Sim",
                "category_fits": True,
                "symptom_fits": False,
                "suggested_category": "",
                "suggested_symptom": "Vandalismo",  # nome em vez do código: vira o código
                "classification_note": "",
                "solution": "câmera nova com caixa antivandalismo",
                "solution_coherent": "yes",
                "solution_note": "",
            },
            "assessment": lambda: {"summary": "resumo", "supplier_message": ""},
        }[task]()
        assert "texto ao lado" in texts or task not in (
            "photos",
        )  # as fotos vão com a pergunta ao lado
        obj = output.model_validate(data)
        return obj, LlmCall(
            task=task,
            model=model,
            start=datetime.now(),
            duration_s=0,
            simulated=True,
            response=data,
        )


def test_sisr_ticket_with_only_a_pdf_report_is_analyzed(cfg, ref, tmp_path):
    """Antes, o chamado com só o PDF voltava no checklist (nenhuma foto); agora as fotos do PDF entram na análise."""
    import shutil

    from atest.pipeline import Orchestrator

    src = cfg.tickets_dir / "04175640"
    if not src.exists():
        pytest.skip("caso 04175640 não gerado (generator/build_salesforce_cases.py)")
    folder = tmp_path / "04175640"
    shutil.copytree(
        src, folder, ignore=shutil.ignore_patterns("*_foto*.jpg", "*.fotos.json")
    )
    model = FakeModel()
    result = Orchestrator(cfg, ref, model, None).analyze(load_ticket(folder))

    photos = [n for n in model.sent["photos"]]
    assert photos == [
        "Relatorio_Atendimento_04175640_p01_foto01.jpg",
        "Relatorio_Atendimento_04175640_p02_foto01.jpg",
        "Relatorio_Atendimento_04175640_p02_foto02.jpg",
    ]
    assert model.sent["documents"] == [
        "Relatorio_Atendimento_04175640.pdf"
    ]  # o PDF segue para a leitura
    assert (
        result.checklist.complete
    ), result.checklist.missing  # antes: devolvido no checklist
    assert result.recommendation != "checklist_returned"
    kinds = [f.kind for f in result.findings]
    assert "report_answer_contradicted" in kinds
    assert "missing_after_photo" not in kinds
    # vandalismo aberto como "Sem imagem": a causa especial errada leva à análise detalhada
    cause = next(f for f in result.findings if f.kind == "cause_miscategorized")
    assert "vandalismo" in cause.evidence and "Cftv / Sem imagem" in cause.evidence
    assert "o correto seria Vandalismo" in cause.evidence
    assert result.recommendation == "detailed_review"
    assert result.coherence and result.coherence["suggested_symptom"] == "vandalismo"
    contradicted = next(p for p in result.photos if p.contradicts_report)
    assert (
        contradicted.page == 2 and "entrada do autoatendimento" in contradicted.context
    )
    assert (
        result.documents[0].answers[0].question == "O equipamento estava vandalizado?"
    )
