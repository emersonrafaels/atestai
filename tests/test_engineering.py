"""Olhar de engenheiro em todos os agentes: cobertura serviço a serviço, contagem obrigatória nas fotos e racional técnico."""

from atest.analysis import AnalysisContext
from atest.assessment import AssessmentWriter
from atest.domain import EvaluatedItem, Match
from atest.llm import LlmSession
from atest.llm_schemas import ItemReview, PhotoAnalysis, QuantityCheck, QuoteReview, ScopeReading
from atest.photos import PhotoStage, countable_items
from atest.quote import QuoteStage
from atest.repository import load_ticket, read_ticket_quote
from atest.score import ScoreCalculator

TASKS = ("identify_attachments", "scope", "quote_review", "photos", "documents", "assessment")


def _items(cfg, ticket: str) -> list[EvaluatedItem]:
    quote = read_ticket_quote(load_ticket(cfg.tickets_dir / ticket))
    return [EvaluatedItem(**i.model_dump(), classification="compliant", reason="", lpu_code="NO_REFERENCE") for i in quote.items]


def _scope(services: list[str]) -> ScopeReading:
    return ScopeReading(
        local="agência", environment="quadro de energia", equipment="", requested_services=services, mentioned_quantities=[],
        acceptance_criteria=[], expected_evidence=[], before_evidence_applicable=True, consistent_with_category_symptom=True,
        coherence_note="", vague_scope=False, vague_reason="",
    )


def test_every_agent_starts_with_the_engineer_view(cfg):
    session = LlmSession(None, cfg, "04159084")
    for task in TASKS:
        assert session.system(task).startswith("Você trabalha com o olhar de um ENGENHEIRO DE MANUTENÇÃO"), task


def test_countable_items_are_the_physical_measured_ones(cfg):
    floor = _items(cfg, "04164650")  # demolição, piso, cimentado e rejunte em m² + deslocamento
    assert [i.n for i in countable_items(floor)] == [i.n for i in floor if i.unit.lower().startswith("m")]
    assert all("desloc" not in i.description.lower() for i in countable_items(floor))
    assert countable_items(_items(cfg, "04159084")) == []  # uma chapa: nada a contar


class QuoteSession:
    def __init__(self, coverage):
        self.coverage, self.text = coverage, ""

    def system(self, task):
        return task

    def ask(self, task, parts, output, system=None, max_tokens=None):
        self.text = parts[0].text
        return QuoteReview(items=[ItemReview(n=1, classification="compliant", reason="", expected_quantity_max=-1, plausible_quantity=True,
                                             duplicate_of=0, lpu_code="NO_REFERENCE")], service_coverage=self.coverage, notes="")


def test_quote_checks_every_requested_service(cfg, ref):
    ch = load_ticket(cfg.tickets_dir / "04159084")
    services = ["Organizar a fiação do quadro", "Instalar chapa de acrílico", "Desativar a medição da ENGIE"]
    coverage = [
        {"n": 1, "service": services[0], "items": [], "covered": "no", "note": "Nenhum item organiza a fiação"},
        {"n": 2, "service": services[1], "items": [1], "covered": "partial", "note": "Protege, mas não organiza os fios"},
    ]
    session = QuoteSession(coverage)
    ctx = AnalysisContext(ticket=ch, session=session, scope=_scope(services))
    QuoteStage(cfg, ref, ScoreCalculator(ref.rubric)).run(ctx)
    assert "SERVIÇOS PEDIDOS" in session.text and "3. Desativar a medição da ENGIE" in session.text
    gap = [f for f in ctx.findings if f.kind == "scope_not_quoted"]
    assert len(gap) == 1 and "Organizar a fiação" in gap[0].evidence and "acrílico" not in gap[0].evidence
    assert any(n.startswith("Coberto só em parte: Instalar chapa") for n in ctx.quote_notes)
    assert any("não conferido contra o orçamento: Desativar a medição" in n for n in ctx.quote_notes)  # o 3º ficou sem resposta
    assert [c.n for c in ctx.service_coverage] == [1, 2]


def test_photos_must_count_measured_items_and_rationale_reaches_the_writer(cfg, ref):
    items = _items(cfg, "04164650")
    first = countable_items(items)[0]
    analysis = PhotoAnalysis(
        photos=[], has_before_photo=True, done_justification="", done_service=Match.UNDETERMINED, items_without_photo=[], notes="",
        problem_assessment="Peças quebradas em pontos espalhados do autoatendimento, com risco de tropeço.",
        quantity_checks=[QuantityCheck(item=first.n, what_was_counted="peças quebradas", per_photo="Anexo 2: 3; Anexo 3: 5", count_seen=8,
                                       estimated_quantity=1.62, reasoning="peças de 45x45 cm")],
    )
    checked = PhotoStage.with_unchecked_items(analysis, items)
    others = [i for i in countable_items(items) if i.n != first.n]
    assert "Quantidade não conferida pelas fotos" in checked.notes and all(f"item {i.n} (" in checked.notes for i in others)

    ctx = AnalysisContext(ticket=load_ticket(cfg.tickets_dir / "04164650"), session=None)
    ctx.items, ctx.photo_analysis = items, checked
    ctx.service_coverage = QuoteReview(items=[], notes="", service_coverage=[
        {"n": 1, "service": "Trocar o piso quebrado", "items": [1, 2], "covered": "yes", "note": ""}]).service_coverage
    ctx.score = ScoreCalculator(ref.rubric).compute([], [], 0)
    text = AssessmentWriter.prompt(ctx.scoring_input())
    assert "RACIONAL TÉCNICO" in text
    assert "“Trocar o piso quebrado”: coberto (itens 1, 2)" in text
    assert f"cobrado {first.quantity:g} {first.unit}; as fotos somam 8 (peças quebradas), cerca de 1.62 {first.unit}" in text
    assert "Nenhum item tem equivalente na tabela de referência" in text
    assert "risco de tropeço" in text
