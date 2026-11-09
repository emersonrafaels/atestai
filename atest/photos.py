"""Validação 3 — Evidências fotográficas: as fotos provam que o serviço foi feito?

- Agente de fotos (modelo principal, visão): o que cada foto mostra, antes/depois, legibilidade, aderência ao escopo,
  cobertura por item e se há prova do serviço concluído.
- Integridade (determinístico, Fase 2): phash + dhash contra fotos de chamados anteriores; data EXIF.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .analysis import AnalysisContext, AnalysisStage
from .attachments import HashCache, Hashes, attachment_parts, compute_hashes, detail_level, distance, exif_date
from .domain import Attachment, ClassifiedAttachment, EvaluatedItem, EvaluatedPhoto, Finding, Match, Moment, Rubric, Stage
from .llm import LlmSession
from .llm_schemas import PhotoAnalysis, ScopeReading
from .providers import Part, TextPart
from .repository import LoadedTicket, load_ticket
from .scope import ScopeStage

DEFAULT_CROPS = [0.02, 0.05, 0.1]


# --------------------------------------------------------------------------- índice de fotos (integridade)
@dataclass(frozen=True)
class IndexedPhoto:
    """Foto já conhecida (histórico ou lote atual), com hashes da foto inteira e de recortes de borda."""

    ticket_id: str
    submission: date
    file: str
    hashes: list[Hashes]
    detail_level: float = 100.0


@dataclass
class PhotoIndex:
    """Hashes das fotos de outros chamados, para detectar reaproveitamento."""

    records: list[IndexedPhoto] = field(default_factory=list)
    crops: list[float] = field(default_factory=lambda: list(DEFAULT_CROPS))
    cache: HashCache = field(default_factory=HashCache)

    @classmethod
    def from_folders(cls, *folders: Path, crops: list[float] | None = None, cache: HashCache | None = None) -> PhotoIndex:
        """Indexa todas as fotos das pastas de chamados (histórico + chamados atuais)."""
        index = cls(crops=crops if crops is not None else list(DEFAULT_CROPS), cache=cache or HashCache())
        for folder in folders:
            if Path(folder).exists():
                index.add_folder(Path(folder))
        index.cache.save()
        return index

    def add_folder(self, tickets_folder: Path) -> None:
        """Indexa as fotos de todos os chamados de uma pasta."""
        for p in sorted(tickets_folder.iterdir()):
            if not (p / "ticket.json").exists():
                continue
            ticket = load_ticket(p)
            for a in ticket.attachments:
                if a.is_image and a.path.exists():
                    hashes, detail = self.cache.get(a.path, self.crops)
                    self.records.append(IndexedPhoto(ticket.id, ticket.data.dates.supplier_submission, a.name, hashes, detail))

    def search(self, ticket_id: str, submission: date, h: Hashes, rubric: Rubric, photo_detail: float = 100.0) -> list[tuple[int, IndexedPhoto]]:
        """Fotos de chamados ANTERIORES parecidas, da mais parecida para a menos.

        Se uma das duas fotos tem pouco detalhe (escura, tremida), vale o limite estrito da régua: só cópia
        praticamente idêntica conta.
        """

        def limit(r: IndexedPhoto) -> int:
            low = min(photo_detail, r.detail_level) < rubric.hash_min_detail
            return rubric.hash_max_distance_low_detail if low else rubric.hash_max_distance

        candidates = (r for r in self.records if r.ticket_id != ticket_id and r.submission <= submission)
        matches = [(min(distance(h, x) for x in r.hashes), r) for r in candidates]
        return sorted([(d, r) for d, r in matches if d <= limit(r)], key=lambda x: x[0])


# --------------------------------------------------------------------------- etapa
class PhotoStage(AnalysisStage):
    """Analisa as fotos com o modelo e verifica a integridade (data e reaproveitamento) por regra."""

    name = "photos"
    progress = Stage.PHOTOS

    def __init__(self, *args, index: PhotoIndex | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.index = index

    def run(self, ctx: AnalysisContext) -> None:
        assert ctx.scope is not None
        ctx.photos = photos = self.ticket_photos(ctx.ticket, ctx.attachments)
        ctx.photo_analysis = analysis = self.analyze(ctx.session, ctx.ticket, ctx.scope, ctx.items, photos) if photos else self.empty_analysis()
        ctx.findings += self.flag(ctx.ticket, ctx.scope, analysis, photos)
        ctx.integrity, integrity_findings = self.integrity(ctx.ticket, photos)
        ctx.findings += integrity_findings

    @staticmethod
    def ticket_photos(ticket: LoadedTicket, attachments: list[ClassifiedAttachment]) -> list[Attachment]:
        """Imagens do chamado, sem as fotos de documentos (termo, relatório)."""
        docs = {a.name for a in attachments if a.category.value.endswith("_doc")}
        return [a for a in ticket.attachments if a.is_image and a.name not in docs]

    @staticmethod
    def empty_analysis() -> PhotoAnalysis:
        """Análise vazia, usada quando o chamado não tem fotos."""
        return PhotoAnalysis(
            photos=[], has_before_photo=False, has_done_service_photo=False, done_justification="Sem fotos", items_without_photo=[], notes=""
        )

    def analyze(
        self, session: LlmSession, ticket: LoadedTicket, scope: ScopeReading, items: list[EvaluatedItem], photos: list[Attachment]
    ) -> PhotoAnalysis:
        """Envia as fotos ao modelo principal com o escopo e os itens do orçamento."""
        item_lines = "\n".join(f"{i.n}. {i.description} ({i.quantity:g} {i.unit})" for i in items) or "(orçamento não lido)"
        content: list[Part] = [
            TextPart(
                f"{ticket.data.summary_text()}\n\nLEITURA DO ESCOPO:\n{ScopeStage.describe(scope)}\n\n"
                f"ITENS DO ORÇAMENTO:\n{item_lines}\n\n{len(photos)} fotos a seguir; use o número do anexo como 'index'."
            )
        ]
        for a in photos:
            content += attachment_parts(a, self.cfg.llm.image_max_side)
        meta = {"attachments": [a.name for a in photos], "indices": [a.index for a in photos]}
        return session.ask("photos", content, PhotoAnalysis, max_tokens=5000, meta=meta)

    def flag(self, ticket: LoadedTicket, scope: ScopeReading, analysis: PhotoAnalysis, photos: list[Attachment]) -> list[Finding]:
        """Apontamentos a partir da análise do modelo: foto que não corresponde, ilegível, sem "depois", sem "antes"."""
        names = {a.index: a.name for a in photos}
        findings = []
        for f in analysis.photos:
            name = names.get(f.index, f"anexo {f.index}")
            if f.readable and f.matches_scope == Match.NO:
                findings.append(self.scorer.finding("photo_mismatch", f"{f.what_it_shows}. {f.reason}", name))
            if not f.readable:
                findings.append(self.scorer.finding("unreadable_photo", f.reason or "Foto escura, tremida ou sem foco", name))
        if ticket.data.moment == Moment.EXECUTION and not analysis.has_done_service_photo:
            findings.append(self.scorer.finding("missing_after_photo", analysis.done_justification or "Nenhuma foto comprova o serviço concluído"))
        if scope.before_evidence_applicable and not analysis.has_before_photo:
            findings.append(self.scorer.finding("missing_before_photo", "Nenhuma foto registra o estado anterior ao serviço"))
        return findings

    def integrity(self, ticket: LoadedTicket, photos: list[Attachment]) -> tuple[dict[str, dict], list[Finding]]:
        """Data EXIF anterior à abertura e semelhança com fotos de chamados anteriores."""
        rubric = self.rubric
        info: dict[str, dict] = {}
        findings: list[Finding] = []
        opening = datetime.combine(ticket.data.dates.opening, datetime.min.time())
        for a in photos:
            signals: list[str] = []
            taken = exif_date(a.path)
            if taken and taken < opening - timedelta(days=rubric.photo_date_tolerance_days):
                msg = f"Data da foto ({taken:%d/%m/%Y}) anterior à abertura do chamado ({opening:%d/%m/%Y})"
                signals.append(msg)
                findings.append(self.scorer.finding("photo_dated_before", msg, a.name))
            origin = None
            if self.index:
                matches = self.index.search(ticket.id, ticket.data.dates.supplier_submission, compute_hashes(a.path), rubric, detail_level(a.path))
                if matches:
                    d, r = matches[0]
                    origin = f"{r.ticket_id}/{r.file}"
                    signals.append(f"Semelhante à foto {r.file} do chamado {r.ticket_id} (distância {d})")
                    findings.append(
                        self.scorer.finding("reused_photo", f"Foto idêntica ou muito semelhante à do chamado {r.ticket_id} ({r.file})", a.name)
                    )
            info[a.name] = {"exif_date": taken, "reused_from": origin, "integrity_signals": signals}
        return info, findings

    @staticmethod
    def evaluated_photos(analysis: PhotoAnalysis, photos: list[Attachment], integrity: dict[str, dict]) -> list[EvaluatedPhoto]:
        """Foto a foto, a leitura do modelo somada aos sinais de integridade (para o parecer e o painel)."""
        names = {a.index: a.name for a in photos}
        out = []
        for f in analysis.photos:
            name = names.get(f.index, f"anexo {f.index}")
            out.append(EvaluatedPhoto(file=name, **f.model_dump(exclude={"index"}), **integrity.get(name, {})))
        return out
