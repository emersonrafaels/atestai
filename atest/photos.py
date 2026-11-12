"""Validação 3 — Evidências fotográficas: as fotos provam que o serviço foi feito?

- Agente de fotos (modelo principal, visão): o que cada foto mostra, antes/depois, legibilidade, aderência ao escopo,
  cobertura por item e se há prova do serviço concluído.
- Integridade (determinístico, Fase 2): phash + dhash contra fotos de chamados anteriores; data EXIF.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .analysis import AnalysisContext, AnalysisStage
from .attachments import HashCache, Hashes, attachment_parts, compute_hashes, detail_level, distance, exif_date
from .domain import Attachment, ClassifiedAttachment, EvaluatedItem, EvaluatedPhoto, Finding, Match, Moment, Rubric, Stage
from .llm import LlmSession, LlmTimeout
from .llm_schemas import PhotoAnalysis, QuantityCheck, ScopeReading
from .observability import event
from .providers import Part, ProviderError, TextPart
from .quote import amount_at_issue
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

    CHUNK = 6  # fotos por chamada quando a análise de todas juntas falha

    def run(self, ctx: AnalysisContext) -> None:
        assert ctx.scope is not None
        ctx.photos = photos = self.ticket_photos(ctx.ticket, ctx.attachments)
        analysis = self.analyze_resilient(ctx.session, ctx.ticket, ctx.scope, ctx.items, photos) if photos else self.empty_analysis()
        if analysis is None:  # o modelo não devolveu leitura válida nem em lotes: segue sem a leitura das fotos
            ctx.photo_analysis = self.unread_analysis(len(photos))
            ctx.confidence_reducers.append("photos_not_analyzed")
        else:
            ctx.photo_analysis = analysis
            ctx.findings += self.flag(ctx.ticket, ctx.scope, analysis, photos, ctx.items)
            ctx.findings += self.quantity_findings(analysis, ctx.items)
        ctx.integrity, integrity_findings = self.integrity(ctx.ticket, photos)  # por regra: vale mesmo sem a leitura do modelo
        ctx.findings += integrity_findings

    def analyze_resilient(
        self, session: LlmSession, ticket: LoadedTicket, scope: ScopeReading, items: list[EvaluatedItem], photos: list[Attachment]
    ) -> PhotoAnalysis | None:
        """Análise das fotos que não derruba o chamado quando a resposta do modelo falha (ex.: saída estruturada da IARA/Bedrock).

        1. todas as fotos numa chamada; 2. se falhar, de novo (falhas de formato costumam ser pontuais); 3. com mais de
        CHUNK fotos, em lotes menores, juntando o resultado; 4. se nada der certo, None (o chamado segue com redutor).
        """
        try:
            return self.analyze(session, ticket, scope, items, photos)
        except ProviderError as e:
            event("photos_retry", logging.WARNING, error=str(e)[:300], photos=len(photos))
            first = e
        if len(photos) <= self.CHUNK:
            if isinstance(first, LlmTimeout):  # API travada: repetir o mesmo pedido só dobraria a espera
                event("photos_degraded", logging.WARNING, error=str(first)[:300], photos=len(photos))
                return None
            try:
                return self.analyze(session, ticket, scope, items, photos)
            except ProviderError as e:
                event("photos_degraded", logging.WARNING, error=str(e)[:300], photos=len(photos))
                return None
        chunks = [photos[i : i + self.CHUNK] for i in range(0, len(photos), self.CHUNK)]
        event("photos_chunked", logging.WARNING, photos=len(photos), chunks=len(chunks), error=str(first)[:300])
        parts: list[PhotoAnalysis] = []
        for n, chunk in enumerate(chunks, 1):
            try:
                parts.append(self.analyze(session, ticket, scope, items, chunk, batch=(n, len(chunks))))
            except ProviderError as e:
                event("photos_degraded", logging.WARNING, error=str(e)[:300], photos=len(chunk), chunk=n)
                return None
        return self.merge(parts)

    @staticmethod
    def unread_analysis(n_photos: int) -> PhotoAnalysis:
        """Sem leitura do modelo: nada é afirmado sobre as fotos (nenhum apontamento sai daqui) e o parecer avisa."""
        note = (f"As {n_photos} fotos não puderam ser analisadas: o modelo não devolveu uma resposta válida depois de novas "
                "tentativas. Confira as fotos manualmente.")
        return PhotoAnalysis(
            photos=[], has_before_photo=False, done_justification=note, done_service=Match.UNDETERMINED, items_without_photo=[],
            quantity_checks=[], notes=note,
        )

    @staticmethod
    def merge(parts: list[PhotoAnalysis]) -> PhotoAnalysis:
        """Junta a análise feita em lotes: fotos somadas, item sem foto só se nenhum lote o cobre, contagens somadas por item."""
        order = [Match.YES, Match.PARTIAL, Match.NO, Match.UNDETERMINED]
        done = min((p.done_service for p in parts), key=order.index)
        missing = set(parts[0].items_without_photo)
        for p in parts[1:]:
            missing &= set(p.items_without_photo)
        checks: dict[int, QuantityCheck] = {}
        for p in parts:
            for c in p.quantity_checks:
                if c.item not in checks:
                    checks[c.item] = c.model_copy()
                    continue
                prev = checks[c.item]
                est = (max(prev.estimated_quantity, 0) + max(c.estimated_quantity, 0)) or -1
                checks[c.item] = prev.model_copy(update={
                    "count_seen": prev.count_seen + c.count_seen, "estimated_quantity": est, "per_photo": f"{prev.per_photo}; {c.per_photo}",
                })
        return PhotoAnalysis(
            photos=[f for p in parts for f in p.photos],
            has_before_photo=any(p.has_before_photo for p in parts),
            done_justification=" ".join(p.done_justification for p in parts if p.done_justification).strip(),
            done_service=done,
            items_without_photo=sorted(missing),
            quantity_checks=list(checks.values()),
            notes=" ".join(p.notes for p in parts if p.notes).strip(),
        )

    @staticmethod
    def ticket_photos(ticket: LoadedTicket, attachments: list[ClassifiedAttachment]) -> list[Attachment]:
        """Imagens do chamado, sem as fotos de documentos (termo, relatório)."""
        docs = {a.name for a in attachments if a.category.value.endswith("_doc")}
        return [a for a in ticket.attachments if a.is_image and a.name not in docs]

    @staticmethod
    def empty_analysis() -> PhotoAnalysis:
        """Análise vazia, usada quando o chamado não tem fotos."""
        return PhotoAnalysis(
            photos=[], has_before_photo=False, done_justification="Sem fotos", done_service=Match.NO, items_without_photo=[],
            quantity_checks=[], notes="",
        )

    def analyze(
        self, session: LlmSession, ticket: LoadedTicket, scope: ScopeReading, items: list[EvaluatedItem], photos: list[Attachment],
        batch: tuple[int, int] | None = None,
    ) -> PhotoAnalysis:
        """Envia as fotos ao modelo principal com o escopo e os itens do orçamento (ou um lote delas, em `batch`)."""
        item_lines = "\n".join(f"{i.n}. {i.description} ({i.quantity:g} {i.unit})" for i in items) or "(orçamento não lido)"
        part = (f"Lote {batch[0]} de {batch[1]} das fotos do chamado: avalie só estas fotos; contagens e itens sem foto se "
                "referem a este lote. ") if batch else ""
        content: list[Part] = [
            TextPart(
                f"{ticket.data.summary_text()}\n\nLEITURA DO ESCOPO:\n{ScopeStage.describe(scope)}\n\n"
                f"ITENS DO ORÇAMENTO:\n{item_lines}\n\n{part}{len(photos)} fotos a seguir; use o número do anexo como 'index'."
            )
        ]
        for a in photos:
            content += attachment_parts(a, self.cfg.llm.image_max_side)
        meta = {"attachments": [a.name for a in photos], "indices": [a.index for a in photos]}
        # a resposta cresce com o número de fotos: limite fixo cortava a saída com muitas fotos
        max_tokens = min(16000, 2500 + 450 * len(photos))
        return session.ask("photos", content, PhotoAnalysis, max_tokens=max_tokens, meta=meta)

    def flag(
        self, ticket: LoadedTicket, scope: ScopeReading, analysis: PhotoAnalysis, photos: list[Attachment], items: list[EvaluatedItem] | None = None
    ) -> list[Finding]:
        """Apontamentos a partir da análise do modelo: foto que não corresponde, ilegível, sem "depois", sem "antes",
        itens cobrados sem evidência.

        Foto do depois que mostra o resultado, mas sem como confirmar o local (comum em agência: um forro é igual ao
        outro), não é "sem foto do serviço": vira um apontamento médio que reduz a confiança, para a pessoa conferir.
        """
        names = {a.index: a.name for a in photos}
        findings = []
        for f in analysis.photos:
            name = names.get(f.index, f"anexo {f.index}")
            if f.readable and f.matches_scope == Match.NO:
                findings.append(self.scorer.finding("photo_mismatch", f"{f.what_it_shows}. {f.reason}", name))
            if not f.readable:
                findings.append(self.scorer.finding("unreadable_photo", f.reason or "Foto escura, tremida ou sem foco", name))
        if ticket.data.moment == Moment.EXECUTION:
            why = analysis.done_justification
            if analysis.done_service == Match.NO:
                findings.append(self.scorer.finding("missing_after_photo", why or "Nenhuma foto comprova o serviço concluído"))
            elif analysis.done_service in (Match.PARTIAL, Match.UNDETERMINED):
                why = why or "A foto mostra o resultado, mas não permite confirmar o local"
                findings.append(self.scorer.finding("after_photo_unconfirmed_location", why))
            if analysis.items_without_photo and analysis.done_service != Match.NO:  # sem prova nenhuma, o "sem foto do depois" já cobre
                findings += self._items_without_photo(analysis.items_without_photo, items or [])
        if scope.before_evidence_applicable and not analysis.has_before_photo:
            findings.append(self.scorer.finding("missing_before_photo", "Nenhuma foto registra o estado anterior ao serviço"))
        return findings

    def quantity_findings(self, analysis: PhotoAnalysis, items: list[EvaluatedItem]) -> list[Finding]:
        """Quantidade cobrada acima do que as fotos mostram (somadas), além da tolerância: apontamento sobre o excedente.

        Ex.: 4,6 m² de piso cobrados e as fotos somam 7 peças quebradas de 45x45 cm (≈ 1,42 m²). Vale também na aprovação
        do orçamento, quando as fotos do antes são a evidência do que precisa ser feito.
        """
        if "quantity_above_photos" not in self.rubric.finding_types:
            return []
        tol = self.rubric.photo_quantity_tolerance_pct / 100
        by_n = {i.n: i for i in items}
        out: list[Finding] = []
        for c in analysis.quantity_checks:
            item = by_n.get(c.item)
            if item is None or c.estimated_quantity <= 0 or item.quantity <= c.estimated_quantity * (1 + tol):
                continue
            excess = round((item.quantity - c.estimated_quantity) * item.unit_value, 2)
            evidence = (
                f"Cobrado {item.quantity:g} {item.unit}; as fotos somam {c.count_seen:g} ({c.what_was_counted}), "
                f"cerca de {c.estimated_quantity:g} {item.unit} ({c.per_photo}). {c.reasoning}"
            )
            f = self.scorer.finding("quantity_above_photos", evidence, f"item {item.n}: {item.description}", excess)
            item.findings.append(f)
            item.amount_at_issue = amount_at_issue(item, item.findings, self.rubric)
            out.append(f)
        return out

    def _items_without_photo(self, numbers: list[int], items: list[EvaluatedItem]) -> list[Finding]:
        """Um apontamento (desconta uma vez) listando os itens físicos cobrados sem foto que os evidencie."""
        by_n = {i.n: i for i in items}
        known = [n for n in sorted(set(numbers)) if not by_n or n in by_n]
        if not known:
            return []
        names = [f"{n}. {by_n[n].description} ({by_n[n].quantity:g} {by_n[n].unit})" if n in by_n else f"item {n}" for n in known]
        evidence = f"Nenhuma foto evidencia: {'; '.join(names)}"
        reference = "itens " + ", ".join(str(n) for n in known) if len(known) > 1 else f"item {known[0]}"
        return [self.scorer.finding("item_without_photo", evidence, reference)]

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
