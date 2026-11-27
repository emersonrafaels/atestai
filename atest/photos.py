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
from .attachments import (
    HashCache,
    Hashes,
    attachment_parts,
    chunked,
    compute_hashes,
    detail_level,
    distance,
    exif_date,
)
from .domain import (
    Attachment,
    ClassifiedAttachment,
    EvaluatedItem,
    EvaluatedPhoto,
    Finding,
    Match,
    Moment,
    Rubric,
    Stage,
    stage_expectations,
)
from .formatting import drop_after_service_requests, normalize_text, normalize_unit
from .llm import LlmSession, LlmTimeout
from .llm_schemas import PhotoAnalysis, QuantityCheck, ScopeReading
from .observability import event
from .providers import Part, ProviderError, TextPart
from .quote import amount_at_issue
from .repository import LoadedTicket, load_ticket
from .scope import ScopeStage

DEFAULT_CROPS = [0.02, 0.05, 0.1]

# Apontamentos que cobram a prova do serviço feito: só valem no retorno após a execução, nunca na aprovação do orçamento.
EXECUTION_ONLY = frozenset(
    {"missing_after_photo", "after_photo_unconfirmed_location", "item_without_photo"}
)

# Itens que o engenheiro sempre confere contando nas fotos: cobrados por área/comprimento/volume, ou por peça com mais de uma.
MEASURED_UNITS = {"m2", "m", "ml", "m3", "mt", "mts", "metro", "metros", "metro linear"}
PIECE_UNITS = {
    "un",
    "und",
    "unid",
    "unidade",
    "unidades",
    "pc",
    "pç",
    "pcs",
    "peca",
    "peça",
    "pecas",
    "peças",
}
# itens que não aparecem na foto, pelo começo da descrição ("Demolição ... com transporte" continua contável)
NOT_VISIBLE = (
    "desloca",
    "visita",
    "mao de obra",
    "frete",
    "transporte",
    "taxa",
    "diaria",
    "art ",
    "projeto",
)


def countable_items(items: list[EvaluatedItem]) -> list[EvaluatedItem]:
    """Itens físicos cuja quantidade dá para conferir pelas fotos (piso em m², rodapé em m, 6 luminárias...).

    Args:
        items: itens avaliados do orçamento.

    Returns:
        Os itens medidos por área/comprimento/volume ou cobrados por peça com quantidade > 1, sem os que não
        aparecem em foto (deslocamento, mão de obra, frete, taxa...).
    """
    out = []
    for i in items:
        desc, unit = normalize_text(i.description), normalize_unit(i.unit)
        # Deslocamento, mão de obra, frete, taxa...: não aparecem em foto.
        if f"{desc} ".startswith(NOT_VISIBLE):
            continue
        # Medidos (m², m, m³) sempre; por peça, só quando há mais de uma (uma peça não tem o que contar).
        if unit in MEASURED_UNITS or (unit in PIECE_UNITS and i.quantity > 1):
            out.append(i)
    return out


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
    def from_folders(
        cls,
        *folders: Path,
        crops: list[float] | None = None,
        cache: HashCache | None = None,
    ) -> PhotoIndex:
        """Indexa todas as fotos das pastas de chamados (histórico + chamados atuais).

        Args:
            folders: pastas que contêm uma subpasta por chamado (pastas inexistentes são ignoradas).
            crops: frações de recorte de borda usadas nos hashes; None usa `DEFAULT_CROPS`.
            cache: cache de hashes em disco (salvo no fim); None cria um em memória.

        Returns:
            O índice com uma entrada por foto.
        """
        index = cls(
            crops=crops if crops is not None else list(DEFAULT_CROPS),
            cache=cache or HashCache(),
        )
        for folder in folders:
            if Path(folder).exists():
                index.add_folder(Path(folder))
        index.cache.save()
        return index

    def add_folder(self, tickets_folder: Path) -> None:
        """Indexa as fotos de todos os chamados de uma pasta."""
        for p in sorted(tickets_folder.iterdir()):
            # Só subpastas que são chamados (têm ticket.json).
            if not (p / "ticket.json").exists():
                continue
            ticket = load_ticket(p)
            for a in ticket.attachments:
                if a.is_image and a.path.exists():
                    # Hashes da foto inteira e dos recortes + nível de detalhe (do cache, se a foto já foi vista).
                    hashes, detail = self.cache.get(a.path, self.crops)
                    self.records.append(
                        IndexedPhoto(
                            ticket.id,
                            ticket.data.dates.supplier_submission,
                            a.name,
                            hashes,
                            detail,
                        )
                    )

    def search(
        self,
        ticket_id: str,
        submission: date,
        h: Hashes,
        rubric: Rubric,
        photo_detail: float = 100.0,
    ) -> list[tuple[int, IndexedPhoto]]:
        """Fotos de chamados ANTERIORES parecidas, da mais parecida para a menos.

        Se uma das duas fotos tem pouco detalhe (escura, tremida), vale o limite estrito da régua: só cópia
        praticamente idêntica conta.

        Args:
            ticket_id: chamado da foto (fotos do próprio chamado não contam).
            submission: data de envio pelo fornecedor (só chamados enviados até essa data contam).
            h: hashes da foto procurada.
            rubric: régua ([hash_max_distance], [hash_max_distance_low_detail], [hash_min_detail]).
            photo_detail: nível de detalhe da foto procurada.

        Returns:
            Pares (distância de Hamming, foto indexada) dentro do limite, da menor distância para a maior.
        """

        def limit(r: IndexedPhoto) -> int:
            # Foto escura/tremida tem hash parecido com qualquer outra foto escura: exige distância bem menor.
            low = min(photo_detail, r.detail_level) < rubric.hash_min_detail
            return (
                rubric.hash_max_distance_low_detail if low else rubric.hash_max_distance
            )

        # Só fotos de OUTROS chamados enviados até a mesma data (a foto original é a mais antiga).
        candidates = (
            r
            for r in self.records
            if r.ticket_id != ticket_id and r.submission <= submission
        )
        # Distância = a menor entre a foto procurada e a foto inteira ou qualquer recorte da candidata.
        matches = [(min(distance(h, x) for x in r.hashes), r) for r in candidates]
        return sorted([(d, r) for d, r in matches if d <= limit(r)], key=lambda x: x[0])


# --------------------------------------------------------------------------- etapa
class PhotoStage(AnalysisStage):
    """Analisa as fotos com o modelo e verifica a integridade (data e reaproveitamento) por regra."""

    name = "photos"
    progress = Stage.PHOTOS

    def __init__(self, *args, index: PhotoIndex | None = None, **kwargs):
        """
        Args:
            *args, **kwargs: os de `AnalysisStage` (cfg, references, scorer).
            index: índice de fotos de outros chamados; None desliga a checagem de reaproveitamento.
        """
        super().__init__(*args, **kwargs)
        self.index = index

    CHUNK = 6  # fotos por chamada quando a análise de todas juntas falha

    def run(self, ctx: AnalysisContext) -> None:
        """Preenche `ctx.photos`, `ctx.photo_analysis` e `ctx.integrity` e acrescenta os apontamentos de fotos.

        Sem leitura válida do modelo, o chamado segue com o redutor "photos_not_analyzed" e nenhum apontamento do
        modelo; a integridade (data EXIF e reaproveitamento) roda por regra de qualquer forma.
        """
        assert ctx.scope is not None
        # Fotos do chamado, sem as que são foto de documento (termo, relatório: vão para a etapa de documentos).
        ctx.photos = photos = self.ticket_photos(ctx.ticket, ctx.attachments)
        # Leitura pelo modelo (com novas tentativas e lotes menores se falhar); sem fotos, análise vazia.
        analysis = (
            self.analyze_resilient(
                ctx.session, ctx.ticket, ctx.scope, ctx.items, photos
            )
            if photos
            else self.empty_analysis()
        )
        if (
            analysis is None
        ):  # o modelo não devolveu leitura válida nem em lotes: segue sem a leitura das fotos
            ctx.photo_analysis = self.unread_analysis(len(photos))
            ctx.confidence_reducers.append("photos_not_analyzed")
        else:
            # Na aprovação do orçamento, apaga o que cobraria o serviço feito.
            ctx.photo_analysis = analysis = self.for_moment(
                analysis, ctx.ticket.data.moment
            )
            # Item que deveria ter sido contado e não foi vira observação.
            ctx.photo_analysis = analysis = self.with_unchecked_items(
                analysis, ctx.items
            )
            # Apontamentos da leitura (foto que não corresponde, ilegível, sem antes/depois, item sem foto)...
            ctx.findings += self.flag(
                ctx.ticket, ctx.scope, analysis, photos, ctx.items
            )
            # ...e de quantidade cobrada acima do que as fotos mostram.
            ctx.findings += self.quantity_findings(analysis, ctx.items)
        ctx.integrity, integrity_findings = self.integrity(
            ctx.ticket, photos
        )  # por regra: vale mesmo sem a leitura do modelo
        ctx.findings += integrity_findings

    def analyze_resilient(
        self,
        session: LlmSession,
        ticket: LoadedTicket,
        scope: ScopeReading,
        items: list[EvaluatedItem],
        photos: list[Attachment],
    ) -> PhotoAnalysis | None:
        """Análise das fotos que não derruba o chamado quando a resposta do modelo falha (ex.: saída estruturada da IARA/Bedrock).

        Mais fotos que [llm.max_images_per_call] (ex.: 100+): direto em lotes desse tamanho, sem a chamada com todas (a
        resposta não caberia no limite de saída); lote que falha é refeito em sublotes de CHUNK.
        Até esse limite: 1. todas as fotos numa chamada; 2. se falhar, de novo (falhas de formato costumam ser pontuais);
        3. com mais de CHUNK fotos, em lotes menores, juntando o resultado. Se nada der certo, None (o chamado segue
        com redutor).

        Args:
            session: sessão de LLM do chamado.
            ticket: chamado.
            scope: leitura do escopo.
            items: itens avaliados do orçamento (para cobertura e contagem).
            photos: fotos a analisar.

        Returns:
            A análise das fotos (juntada, se feita em lotes); None se o modelo não devolveu resposta válida.
        """
        # Muitas fotos: lotes desde o início (a chamada com todas seria cortada no limite de tokens de saída).
        size = self.cfg.llm.max_images_per_call
        if len(photos) > size:
            chunks = chunked(photos, size)
            event(
                "photos_chunked",
                photos=len(photos),
                chunks=len(chunks),
                proactive=True,
            )
            return self._analyze_chunks(
                session, ticket, scope, items, chunks, resplit=True
            )
        # 1ª tentativa: todas as fotos numa chamada só.
        try:
            return self.analyze(session, ticket, scope, items, photos)
        except ProviderError as e:
            event(
                "photos_retry", logging.WARNING, error=str(e)[:300], photos=len(photos)
            )
            first = e
        # Poucas fotos: não adianta dividir; tenta mais uma vez inteiro (exceto se a API travou).
        if len(photos) <= self.CHUNK:
            if isinstance(
                first, LlmTimeout
            ):  # API travada: repetir o mesmo pedido só dobraria a espera
                event(
                    "photos_degraded",
                    logging.WARNING,
                    error=str(first)[:300],
                    photos=len(photos),
                )
                return None
            try:
                return self.analyze(session, ticket, scope, items, photos)
            except ProviderError as e:
                event(
                    "photos_degraded",
                    logging.WARNING,
                    error=str(e)[:300],
                    photos=len(photos),
                )
                return None
        # Mais de CHUNK fotos: divide em lotes de CHUNK.
        chunks = chunked(photos, self.CHUNK)
        event(
            "photos_chunked",
            logging.WARNING,
            photos=len(photos),
            chunks=len(chunks),
            error=str(first)[:300],
        )
        return self._analyze_chunks(session, ticket, scope, items, chunks)

    def _analyze_chunks(
        self,
        session: LlmSession,
        ticket: LoadedTicket,
        scope: ScopeReading,
        items: list[EvaluatedItem],
        chunks: list[list[Attachment]],
        resplit: bool = False,
    ) -> PhotoAnalysis | None:
        """Analisa lote a lote e junta o resultado; basta um lote falhar de vez para desistir (resultado parcial enganaria).

        Args:
            chunks: as fotos já divididas em lotes.
            resplit: True refaz o lote que falhou em sublotes de CHUNK antes de desistir (exceto se a API travou).

        Returns:
            A análise juntada (`merge`); None se algum lote (ou sublote) não teve resposta válida.
        """
        parts = self._chunk_parts(session, ticket, scope, items, chunks, resplit)
        return self.merge(parts) if parts is not None else None

    def _chunk_parts(
        self,
        session: LlmSession,
        ticket: LoadedTicket,
        scope: ScopeReading,
        items: list[EvaluatedItem],
        chunks: list[list[Attachment]],
        resplit: bool,
    ) -> list[PhotoAnalysis] | None:
        """A leitura de cada lote (sublotes no lugar do lote que falhou), ou None se algum falhou de vez."""
        total = len(chunks)
        parts: list[PhotoAnalysis] = []
        for n, chunk in enumerate(chunks, 1):
            try:
                parts.append(
                    self.analyze(session, ticket, scope, items, chunk, batch=(n, total))
                )
                continue
            except ProviderError as e:
                if not resplit or len(chunk) <= self.CHUNK or isinstance(e, LlmTimeout):
                    event(
                        "photos_degraded",
                        logging.WARNING,
                        error=str(e)[:300],
                        photos=len(chunk),
                        chunk=n,
                    )
                    return None
                event(
                    "photos_chunk_split",
                    logging.WARNING,
                    error=str(e)[:300],
                    photos=len(chunk),
                    chunk=n,
                )
            # O lote falhou: refaz em sublotes menores (falha costuma ser resposta cortada ou fora do formato).
            sub = self._chunk_parts(
                session, ticket, scope, items, chunked(chunk, self.CHUNK), False
            )
            if sub is None:
                return None
            parts += sub
        return parts

    @staticmethod
    def with_unchecked_items(
        analysis: PhotoAnalysis, items: list[EvaluatedItem]
    ) -> PhotoAnalysis:
        """Item que devia ter sido contado nas fotos e não foi: fica registrado nas observações (nada passa calado)."""
        checked = {c.item for c in analysis.quantity_checks}
        missing = [i for i in countable_items(items) if i.n not in checked]
        if not missing:
            return analysis
        event(
            "photos_quantity_unchecked", logging.WARNING, items=[i.n for i in missing]
        )
        names = "; ".join(
            f"item {i.n} ({i.description}, {i.quantity:g} {i.unit})" for i in missing
        )
        note = f"Quantidade não conferida pelas fotos: {names}."
        return analysis.model_copy(update={"notes": f"{analysis.notes} {note}".strip()})

    @staticmethod
    def for_moment(analysis: PhotoAnalysis, moment: Moment) -> PhotoAnalysis:
        """Na aprovação do orçamento o serviço ainda não foi feito: nada de "resultado não comprovado" nem de cobrança do
        depois, mesmo que o modelo tenha respondido como se fosse a atestação."""
        if moment != Moment.QUOTE:
            return analysis
        return analysis.model_copy(
            update={
                "done_service": Match.UNDETERMINED,
                "done_justification": "",
                "items_without_photo": [],
                "notes": drop_after_service_requests(analysis.notes),
            }
        )

    @staticmethod
    def unread_analysis(n_photos: int) -> PhotoAnalysis:
        """Sem leitura do modelo: nada é afirmado sobre as fotos (nenhum apontamento sai daqui) e o parecer avisa."""
        note = (
            f"As {n_photos} fotos não puderam ser analisadas: o modelo não devolveu uma resposta válida depois de novas "
            "tentativas. Confira as fotos manualmente."
        )
        return PhotoAnalysis(
            photos=[],
            has_before_photo=False,
            done_justification=note,
            done_service=Match.UNDETERMINED,
            items_without_photo=[],
            quantity_checks=[],
            notes=note,
        )

    @staticmethod
    def merge(parts: list[PhotoAnalysis]) -> PhotoAnalysis:
        """Junta a análise feita em lotes: fotos somadas, item sem foto só se nenhum lote o cobre, contagens somadas por item."""
        # Serviço comprovado: vale o melhor resultado entre os lotes (basta um lote mostrar o serviço feito).
        order = [Match.YES, Match.PARTIAL, Match.NO, Match.UNDETERMINED]
        done = min((p.done_service for p in parts), key=order.index)
        # Item sem foto: só se nenhum lote tiver foto dele (interseção).
        missing = set(parts[0].items_without_photo)
        for p in parts[1:]:
            missing &= set(p.items_without_photo)
        # Contagens: somadas por item entre os lotes (-1 = "não deu para estimar" quando nenhum lote estimou).
        checks: dict[int, QuantityCheck] = {}
        for p in parts:
            for c in p.quantity_checks:
                if c.item not in checks:
                    checks[c.item] = c.model_copy()
                    continue
                prev = checks[c.item]
                est = (
                    max(prev.estimated_quantity, 0) + max(c.estimated_quantity, 0)
                ) or -1
                checks[c.item] = prev.model_copy(
                    update={
                        "count_seen": prev.count_seen + c.count_seen,
                        "estimated_quantity": est,
                        "per_photo": f"{prev.per_photo}; {c.per_photo}",
                    }
                )

        # Textos livres: um trecho por lote; com mais de um lote, cada trecho diz de que fotos fala ("Fotos 21–40:").
        def joined(field: str) -> str:
            out = []
            for p in parts:
                text = getattr(p, field).strip()
                if not text:
                    continue
                idx = [f.index for f in p.photos]
                if len(parts) > 1 and idx:
                    lo, hi = min(idx), max(idx)
                    text = (
                        f"Fotos {lo}–{hi}: {text}" if lo != hi else f"Foto {lo}: {text}"
                    )
                out.append(text)
            return " ".join(out)

        return PhotoAnalysis(
            photos=[f for p in parts for f in p.photos],
            has_before_photo=any(p.has_before_photo for p in parts),
            problem_assessment=joined("problem_assessment"),
            done_justification=joined("done_justification"),
            done_service=done,
            items_without_photo=sorted(missing),
            quantity_checks=list(checks.values()),
            notes=joined("notes"),
        )

    @staticmethod
    def ticket_photos(
        ticket: LoadedTicket, attachments: list[ClassifiedAttachment]
    ) -> list[Attachment]:
        """Imagens do chamado, sem as fotos de documentos (termo, relatório)."""
        docs = {a.name for a in attachments if a.category.value.endswith("_doc")}
        return [a for a in ticket.attachments if a.is_image and a.name not in docs]

    @staticmethod
    def empty_analysis() -> PhotoAnalysis:
        """Análise vazia, usada quando o chamado não tem fotos."""
        return PhotoAnalysis(
            photos=[],
            has_before_photo=False,
            done_justification="Sem fotos",
            done_service=Match.NO,
            items_without_photo=[],
            quantity_checks=[],
            notes="",
        )

    def analyze(
        self,
        session: LlmSession,
        ticket: LoadedTicket,
        scope: ScopeReading,
        items: list[EvaluatedItem],
        photos: list[Attachment],
        batch: tuple[int, int] | None = None,
    ) -> PhotoAnalysis:
        """Envia as fotos ao modelo principal com o escopo e os itens do orçamento (ou um lote delas, em `batch`).

        Args:
            session: sessão de LLM do chamado.
            ticket: chamado (resumo e etapa: aprovação do orçamento ou atestação).
            scope: leitura do escopo.
            items: itens do orçamento; os contáveis (`countable_items`) pedem uma contagem nas fotos.
            photos: fotos enviadas nesta chamada.
            batch: (número do lote, total de lotes) quando as fotos vão em partes; None = todas juntas.

        Returns:
            A leitura do modelo: foto a foto, antes/depois, serviço comprovado, itens sem foto e contagens.
            O limite de tokens cresce com o número de fotos (até 16 mil).

        Raises:
            ProviderError: resposta inválida, cortada ou sem resposta do modelo.

        Os argumentos passados ao session.ask:
            task: "photos".
            parts: resumo do chamado + escopo + itens + o que se espera nesta etapa + itens a contar + as fotos.
            output: `PhotoAnalysis`.
            max_tokens: 2500 + 450 por foto, até 16 mil; usa o modelo principal (visão).
            meta: nomes e números das fotos enviadas, para o rastro.
        """
        # Itens do orçamento (para o modelo ligar cada foto ao que foi cobrado).
        item_lines = (
            "\n".join(
                f"{i.n}. {i.description} ({i.quantity:g} {i.unit})" for i in items
            )
            or "(orçamento não lido)"
        )
        # Itens físicos que o modelo deve contar nas fotos (um quantity_check por item).
        to_count = countable_items(items)
        count_lines = (
            (
                "ITENS A CONTAR NAS FOTOS (um quantity_check para cada, somando as fotos; -1 se não der para contar):\n"
                + "\n".join(
                    f"{i.n}. {i.description}: cobrado {i.quantity:g} {i.unit}"
                    for i in to_count
                )
                + "\n\n"
            )
            if to_count
            else ""
        )
        part = (
            (
                f"Lote {batch[0]} de {batch[1]} das fotos do chamado: avalie só estas fotos; contagens e itens sem foto se "
                "referem a este lote. "
            )
            if batch
            else ""
        )
        content: list[Part] = [
            TextPart(
                f"{ticket.data.summary_text()}\n\nLEITURA DO ESCOPO:\n{ScopeStage.describe(scope)}\n\n"
                f"ITENS DO ORÇAMENTO:\n{item_lines}\n\nLEMBRE A ETAPA: {stage_expectations(ticket.data.moment)}\n\n"
                f"{count_lines}{part}{len(photos)} fotos a seguir; use o número do anexo como 'index'."
            )
        ]
        for a in photos:
            content += attachment_parts(a, self.cfg.llm.image_max_side)
        meta = {
            "attachments": [a.name for a in photos],
            "indices": [a.index for a in photos],
        }
        # a resposta cresce com o número de fotos: limite fixo cortava a saída com muitas fotos
        max_tokens = min(16000, 2500 + 450 * len(photos))
        return session.ask(
            "photos", content, PhotoAnalysis, max_tokens=max_tokens, meta=meta
        )

    def flag(
        self,
        ticket: LoadedTicket,
        scope: ScopeReading,
        analysis: PhotoAnalysis,
        photos: list[Attachment],
        items: list[EvaluatedItem] | None = None,
    ) -> list[Finding]:
        """Apontamentos a partir da análise do modelo: foto que não corresponde, ilegível, sem "depois", sem "antes",
        itens cobrados sem evidência.

        Foto do depois que mostra o resultado, mas sem como confirmar o local (comum em agência: um forro é igual ao
        outro), não é "sem foto do serviço": vira um apontamento médio que reduz a confiança, para a pessoa conferir.

        Args:
            ticket: chamado (os apontamentos do "depois" só valem na atestação).
            scope: leitura do escopo (diz se a foto do "antes" se aplica).
            analysis: leitura das fotos pelo modelo.
            photos: fotos enviadas (para trocar o número do anexo pelo nome do arquivo).
            items: itens do orçamento, para descrever os itens sem foto.

        Returns:
            Os apontamentos das fotos.
        """
        by_index = {a.index: a for a in photos}
        findings = []
        # Foto a foto: legível mas de outro ambiente/serviço, ou ilegível.
        for f in analysis.photos:
            a = by_index.get(f.index)
            name = a.name if a else f"anexo {f.index}"
            # Foto de relatório em PDF (pergunta + Sim/Não + foto) que contradiz a resposta marcada.
            if (
                a
                and getattr(a, "source", "")
                and f.readable
                and f.contradicts_report.strip()
                and "report_answer_contradicted" in self.rubric.finding_types
            ):
                where = f"página {a.page} do {a.source}"
                said = f' ("{a.context}")' if a.context else ""
                findings.append(
                    self.scorer.finding(
                        "report_answer_contradicted",
                        f"{f.contradicts_report.strip()} ({where}{said})",
                        name,
                    )
                )
            if f.readable and f.matches_scope == Match.NO:
                findings.append(
                    self.scorer.finding(
                        "photo_mismatch", f"{f.what_it_shows}. {f.reason}", name
                    )
                )
            if not f.readable:
                findings.append(
                    self.scorer.finding(
                        "unreadable_photo",
                        f.reason or "Foto escura, tremida ou sem foco",
                        name,
                    )
                )
        # Só na atestação (serviço já feito): as fotos precisam provar o resultado.
        if ticket.data.moment == Moment.EXECUTION:
            why = analysis.done_justification
            if analysis.done_service == Match.NO:
                findings.append(
                    self.scorer.finding(
                        "missing_after_photo",
                        why or "Nenhuma foto comprova o serviço concluído",
                    )
                )
            elif analysis.done_service in (Match.PARTIAL, Match.UNDETERMINED):
                why = (
                    why
                    or "A foto mostra o resultado, mas não permite confirmar o local"
                )
                findings.append(
                    self.scorer.finding("after_photo_unconfirmed_location", why)
                )
            if (
                analysis.items_without_photo and analysis.done_service != Match.NO
            ):  # sem prova nenhuma, o "sem foto do depois" já cobre
                findings += self._items_without_photo(
                    analysis.items_without_photo, items or []
                )
        # Foto do antes: cobrada só quando faz sentido para o serviço (a leitura do escopo decide).
        if scope.before_evidence_applicable and not analysis.has_before_photo:
            findings.append(
                self.scorer.finding(
                    "missing_before_photo",
                    "Nenhuma foto registra o estado anterior ao serviço",
                )
            )
        return findings

    def quantity_findings(
        self, analysis: PhotoAnalysis, items: list[EvaluatedItem]
    ) -> list[Finding]:
        """Quantidade cobrada acima do que as fotos mostram (somadas), além da tolerância: apontamento sobre o excedente.

        Ex.: 4,6 m² de piso cobrados e as fotos somam 7 peças quebradas de 45x45 cm (≈ 1,42 m²). Vale também na aprovação
        do orçamento, quando as fotos do antes são a evidência do que precisa ser feito.

        Args:
            analysis: leitura das fotos, com as contagens por item.
            items: itens avaliados; o apontamento também é anexado ao item e o valor em questão do item é refeito.

        Returns:
            Um `quantity_above_photos` por item cobrado acima da estimativa + [photo_quantity_tolerance_pct].
        """
        if "quantity_above_photos" not in self.rubric.finding_types:
            return []
        tol = self.rubric.photo_quantity_tolerance_pct / 100
        by_n = {i.n: i for i in items}
        out: list[Finding] = []
        for c in analysis.quantity_checks:
            item = by_n.get(c.item)
            # Ignora: item desconhecido, modelo não conseguiu estimar (≤ 0) ou cobrado dentro da tolerância.
            if (
                item is None
                or c.estimated_quantity <= 0
                or item.quantity <= c.estimated_quantity * (1 + tol)
            ):
                continue
            # Valor em questão = quantidade a mais que as fotos mostram × preço unitário.
            excess = round((item.quantity - c.estimated_quantity) * item.unit_value, 2)
            evidence = (
                f"Cobrado {item.quantity:g} {item.unit}; as fotos somam {c.count_seen:g} ({c.what_was_counted}), "
                f"cerca de {c.estimated_quantity:g} {item.unit} ({c.per_photo}). {c.reasoning}"
            )
            f = self.scorer.finding(
                "quantity_above_photos",
                evidence,
                f"item {item.n}: {item.description}",
                excess,
            )
            # O apontamento também fica no item, e o valor em questão do item é refeito com ele.
            item.findings.append(f)
            item.amount_at_issue = amount_at_issue(item, item.findings, self.rubric)
            out.append(f)
        return out

    def _items_without_photo(
        self, numbers: list[int], items: list[EvaluatedItem]
    ) -> list[Finding]:
        """Um apontamento (desconta uma vez) listando os itens físicos cobrados sem foto que os evidencie."""
        by_n = {i.n: i for i in items}
        known = [n for n in sorted(set(numbers)) if not by_n or n in by_n]
        if not known:
            return []
        names = [
            (
                f"{n}. {by_n[n].description} ({by_n[n].quantity:g} {by_n[n].unit})"
                if n in by_n
                else f"item {n}"
            )
            for n in known
        ]
        evidence = f"Nenhuma foto evidencia: {'; '.join(names)}"
        reference = (
            "itens " + ", ".join(str(n) for n in known)
            if len(known) > 1
            else f"item {known[0]}"
        )
        return [self.scorer.finding("item_without_photo", evidence, reference)]

    def integrity(
        self, ticket: LoadedTicket, photos: list[Attachment]
    ) -> tuple[dict[str, dict], list[Finding]]:
        """Data EXIF anterior à abertura e semelhança com fotos de chamados anteriores.

        Args:
            ticket: chamado (data de abertura e de envio pelo fornecedor).
            photos: fotos do chamado.

        Returns:
            (nome da foto → {"exif_date", "reused_from", "integrity_signals"}; apontamentos `photo_dated_before`
            e `reused_photo`). A tolerância de data vem de [photo_date_tolerance_days].
        """
        rubric = self.rubric
        info: dict[str, dict] = {}
        findings: list[Finding] = []
        opening = datetime.combine(ticket.data.dates.opening, datetime.min.time())
        for a in photos:
            signals: list[str] = []
            # Data EXIF (quando a câmera grava): foto tirada antes da abertura do chamado, além da tolerância.
            taken = exif_date(a.path)
            if taken and taken < opening - timedelta(
                days=rubric.photo_date_tolerance_days
            ):
                msg = f"Data da foto ({taken:%d/%m/%Y}) anterior à abertura do chamado ({opening:%d/%m/%Y})"
                signals.append(msg)
                findings.append(self.scorer.finding("photo_dated_before", msg, a.name))
            origin = None
            # Reaproveitamento (Fase 2): procura a foto entre as de chamados anteriores; vale a mais parecida.
            if self.index:
                matches = self.index.search(
                    ticket.id,
                    ticket.data.dates.supplier_submission,
                    compute_hashes(a.path),
                    rubric,
                    detail_level(a.path),
                )
                if matches:
                    d, r = matches[0]
                    origin = f"{r.ticket_id}/{r.file}"
                    signals.append(
                        f"Semelhante à foto {r.file} do chamado {r.ticket_id} (distância {d})"
                    )
                    findings.append(
                        self.scorer.finding(
                            "reused_photo",
                            f"Foto idêntica ou muito semelhante à do chamado {r.ticket_id} ({r.file})",
                            a.name,
                        )
                    )
            info[a.name] = {
                "exif_date": taken,
                "reused_from": origin,
                "integrity_signals": signals,
            }
        return info, findings

    @staticmethod
    def evaluated_photos(
        analysis: PhotoAnalysis, photos: list[Attachment], integrity: dict[str, dict]
    ) -> list[EvaluatedPhoto]:
        """Foto a foto, a leitura do modelo somada aos sinais de integridade (para o parecer e o painel)."""
        by_index = {a.index: a for a in photos}
        out = []
        for f in analysis.photos:
            a = by_index.get(f.index)
            name = a.name if a else f"anexo {f.index}"
            origin = (
                {"source": a.source, "page": a.page, "context": a.context}
                if a and getattr(a, "source", "")
                else {}
            )
            out.append(
                EvaluatedPhoto(
                    file=name,
                    **f.model_dump(exclude={"index"}),
                    **integrity.get(name, {}),
                    **origin,
                )
            )
        return out
