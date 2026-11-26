"""Etapa de fotos resiliente: resposta fora do padrão (IARA/Bedrock), nova tentativa, lotes e análise sem as fotos."""

import json
from types import SimpleNamespace

import pytest

from atest.llm import LlmTimeout
from atest.llm_schemas import AnalyzedPhoto, PhotoAnalysis, QuantityCheck
from atest.photos import PhotoStage
from atest.providers import ProviderError
from atest.providers.iara import extract_json, parse_output
from atest.repository import load_ticket
from atest.score import ScoreCalculator


def test_extract_json_with_text_around():
    assert extract_json('Segue a análise:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json(
        'Claro! Aqui está: {"a": "texto com } e {", "b": [1, 2]} Espero ter ajudado.'
    ) == {"a": "texto com } e {", "b": [1, 2]}
    with pytest.raises(ValueError):
        extract_json("sem json nenhum")


def test_parse_output_normalizes_bedrock_style_answer():
    messy = {
        "photos": [
            {
                "index": "Anexo 3",
                "environment": "autoatendimento",
                "what_it_shows": "piso quebrado",
                "moment": "Antes",
                "readable": "sim",
                "matches_scope": "Parcial",
                "reason": None,
                "covered_items": ["1", "2"],
                "confidence": "alta",
            }
        ],
        "has_before_photo": "Sim",
        "done_justification": "x",
        "done_service": "Não",
        "items_without_photo": None,
        "quantity_checks": [
            {
                "item": "item 1",
                "what_was_counted": "peças",
                "per_photo": "Anexo 3: 2",
                "count_seen": "2",
                "estimated_quantity": "1,42",
                "reasoning": "45x45",
            }
        ],
        "notes": "",
    }
    obj, repairs = parse_output(json.loads(json.dumps(messy)), PhotoAnalysis)
    p = obj.photos[0]
    assert (
        p.index,
        p.moment,
        p.readable,
        p.matches_scope,
        p.reason,
        p.covered_items,
    ) == (3, "before", True, "partial", "", [1, 2])
    assert (
        obj.has_before_photo is True
        and obj.done_service == "no"
        and obj.items_without_photo == []
    )
    assert (
        obj.quantity_checks[0].item == 1
        and obj.quantity_checks[0].estimated_quantity == 1.42
    )
    assert any("descartado" in r for r in repairs)  # campo extra "confidence"


def analysis(
    indices: list[int],
    done: str = "yes",
    missing: list[int] | None = None,
    count: float = 0,
) -> PhotoAnalysis:
    photos = [
        AnalyzedPhoto(
            index=i,
            environment="",
            what_it_shows=f"foto {i}",
            moment="before",
            readable=True,
            matches_scope="yes",
            reason="",
            covered_items=[],
        )
        for i in indices
    ]
    checks = (
        [
            QuantityCheck(
                item=1,
                what_was_counted="peças",
                per_photo=f"lote {indices[0]}",
                count_seen=count,
                estimated_quantity=count * 0.2,
                reasoning="",
            )
        ]
        if count
        else []
    )
    return PhotoAnalysis(
        photos=photos,
        has_before_photo=True,
        done_justification="",
        done_service=done,
        items_without_photo=missing or [],
        quantity_checks=checks,
        notes="",
    )


class FlakySession:
    """Sessão falsa: falha nas primeiras `fails` chamadas e depois responde com as fotos pedidas."""

    def __init__(self, fails: int, error: Exception | None = None):
        self.fails, self.error, self.calls = (
            fails,
            error or ProviderError("[photos] resposta fora do schema PhotoAnalysis"),
            [],
        )

    def ask(self, task, content, output, max_tokens, meta):
        self.calls.append(len(meta["indices"]))
        if len(self.calls) <= self.fails:
            raise self.error
        return analysis(meta["indices"], missing=[2], count=len(meta["indices"]))


@pytest.fixture()
def stage(cfg, ref):
    return PhotoStage(cfg, ref, ScoreCalculator(ref.rubric))


def photos(n: int):
    return [
        SimpleNamespace(
            index=i,
            name=f"f{i}.jpg",
            path=None,
            content_type="image/jpeg",
            is_image=True,
        )
        for i in range(1, n + 1)
    ]


def test_retry_then_chunks_then_merge(stage, monkeypatch):
    ch = load_ticket(stage.cfg.tickets_dir / "04164650")
    monkeypatch.setattr("atest.photos.attachment_parts", lambda a, side: [])
    monkeypatch.setattr(
        "atest.photos.ScopeStage.describe", staticmethod(lambda scope: "(escopo)")
    )
    s = FlakySession(fails=1)
    assert len(
        stage.analyze_resilient(s, ch, scope_stub(), [], photos(4)).photos
    ) == 4 and s.calls == [
        4,
        4,
    ]  # 2ª tentativa
    s = FlakySession(fails=1)
    merged = stage.analyze_resilient(s, ch, scope_stub(), [], photos(13))
    assert s.calls == [13, 6, 6, 1]  # todas juntas falham → 3 lotes de até 6
    assert [p.index for p in merged.photos] == list(
        range(1, 14)
    ) and merged.items_without_photo == [2]
    assert merged.quantity_checks[0].count_seen == 13  # contagem somada entre os lotes
    assert (
        stage.analyze_resilient(FlakySession(fails=99), ch, scope_stub(), [], photos(4))
        is None
    )
    timeout = FlakySession(
        fails=99, error=LlmTimeout("[photos] O modelo não respondeu em 257 s")
    )
    assert stage.analyze_resilient(
        timeout, ch, scope_stub(), [], photos(4)
    ) is None and timeout.calls == [
        4
    ]  # sem repetir o mesmo pedido


class BigBatchFails(FlakySession):
    """Sessão falsa que falha (resposta cortada) em qualquer chamada com mais de `limit` fotos."""

    def __init__(self, limit: int, also_fail_at: int | None = None):
        super().__init__(fails=0, error=ProviderError("cortada", truncated=True))
        self.limit, self.also_fail_at = limit, also_fail_at

    def ask(self, task, content, output, max_tokens, meta):
        self.calls.append(len(meta["indices"]))
        if len(meta["indices"]) > self.limit or len(self.calls) == self.also_fail_at:
            raise self.error
        return analysis(meta["indices"], missing=[2], count=len(meta["indices"]))


@pytest.fixture()
def no_parts(monkeypatch):
    monkeypatch.setattr("atest.photos.attachment_parts", lambda a, side: [])
    monkeypatch.setattr(
        "atest.photos.ScopeStage.describe", staticmethod(lambda scope: "(escopo)")
    )


def test_many_photos_go_straight_to_chunks(stage, no_parts, monkeypatch):
    monkeypatch.setattr(stage.cfg.llm, "max_images_per_call", 20)
    ch = load_ticket(stage.cfg.tickets_dir / "04164650")
    s = FlakySession(fails=0)
    merged = stage.analyze_resilient(s, ch, scope_stub(), [], photos(45))
    assert s.calls == [20, 20, 5]  # sem a chamada com as 45 fotos juntas
    assert [p.index for p in merged.photos] == list(range(1, 46))
    assert merged.quantity_checks[0].count_seen == 45


def test_failed_chunk_is_resplit(stage, no_parts, monkeypatch):
    monkeypatch.setattr(stage.cfg.llm, "max_images_per_call", 20)
    ch = load_ticket(stage.cfg.tickets_dir / "04164650")
    s = BigBatchFails(limit=6)
    merged = stage.analyze_resilient(s, ch, scope_stub(), [], photos(25))
    # lote de 20 cortado → 6+6+6+2; lote de 5 passa direto
    assert s.calls == [20, 6, 6, 6, 2, 5]
    assert [p.index for p in merged.photos] == list(range(1, 26))
    # sublote que também falha: desiste (resultado parcial enganaria)
    s = BigBatchFails(limit=6, also_fail_at=3)
    assert stage.analyze_resilient(s, ch, scope_stub(), [], photos(25)) is None


def test_merge_labels_text_by_photo_range(stage):
    a = analysis([1, 2]).model_copy(update={"notes": "nota A"})
    b = analysis([3]).model_copy(update={"notes": "nota B"})
    assert stage.merge([a, b]).notes == "Fotos 1–2: nota A Foto 3: nota B"
    assert stage.merge([a]).notes == "nota A"  # um lote só: sem prefixo


def test_checklist_identifies_attachments_in_chunks(cfg, ref, monkeypatch):
    from atest.checklist import ChecklistStage
    from atest.llm_schemas import AttachmentIdentification, IdentifiedAttachment

    monkeypatch.setattr(cfg.llm, "max_images_per_call", 20)
    monkeypatch.setattr("atest.checklist.attachment_parts", lambda a, side: [])
    stage = ChecklistStage(cfg, ref, ScoreCalculator(ref.rubric))
    ch = load_ticket(cfg.tickets_dir / "04164650")

    class Session:
        def __init__(self, limit):
            self.limit, self.calls, self.tokens = limit, [], []

        def ask(self, task, content, output, fast, max_tokens, meta):
            self.calls.append(len(meta["indices"]))
            self.tokens.append(max_tokens)
            if len(meta["indices"]) > self.limit:
                raise ProviderError("cortada", truncated=True)
            return AttachmentIdentification(
                attachments=[
                    IdentifiedAttachment(
                        index=i,
                        category="room_after_photo",
                        moment="after",
                        readable=True,
                        short_description=f"foto {i}",
                    )
                    for i in meta["indices"]
                ]
            )

    s = Session(limit=99)
    out = stage._classify_with_model(s, ch, photos(105))
    assert s.calls == [20] * 5 + [5]  # 105 anexos nunca numa chamada só
    assert max(s.tokens) <= 3000
    assert [a.index for a in out] == list(range(1, 106))
    assert all(a.short_description != "não identificado" for a in out)
    # lote cortado: dividido ao meio até caber
    s = Session(limit=10)
    out = stage._classify_with_model(s, ch, photos(25))
    assert s.calls == [20, 10, 10, 5]
    assert [a.index for a in out] == list(range(1, 26))
    # lote mínimo ainda falhando: repassa o erro (não devolve o chamado por anexo "não identificado")
    with pytest.raises(ProviderError):
        stage._classify_with_model(Session(limit=0), ch, photos(25))


def test_unread_photos_keep_ticket_going(stage, monkeypatch):
    from atest.analysis import AnalysisContext

    ch = load_ticket(stage.cfg.tickets_dir / "04164650")
    monkeypatch.setattr(PhotoStage, "analyze_resilient", lambda self, *a: None)
    ctx = AnalysisContext(ticket=ch, session=None, scope=scope_stub())
    stage.run(ctx)
    assert "photos_not_analyzed" in ctx.confidence_reducers
    assert not [
        f for f in ctx.findings if f.validation == "photos" and f.kind != "reused_photo"
    ]  # nada inventado sem leitura
    assert "não puderam ser analisadas" in ctx.photo_analysis.notes
    assert (
        ScoreCalculator(stage.rubric).reducer_label("photos_not_analyzed")
        == "fotos não analisadas pelo modelo"
    )


def scope_stub():
    return SimpleNamespace(before_evidence_applicable=True)
