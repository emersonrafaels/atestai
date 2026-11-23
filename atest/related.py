"""Chamados da mesma agência: o chamado em análise é duplicado de outro já aberto?

É comum a agência abrir mais de um chamado para o mesmo problema (pessoas diferentes, reabertura, pedido repetido por
urgência, categoria escolhida diferente). Esta etapa procura, por regra, os chamados da MESMA agência (mesmo código; sem
código, mesmo nome) que entram na comparação ([rubric.related_tickets]):

- abertos até `window_days` dias antes ou depois da abertura deste;
- com `include_still_open`, os que seguem abertos (situação fora de `closed_statuses`), abertos antes da janela.

O modelo lê os escopos e diz a chance de cada um ser o mesmo problema; a régua decide: a partir de `min_probability`
vira o apontamento `possible_duplicate_ticket` (que leva à análise detalhada), e a partir de `show_probability` o chamado
aparece no parecer como relacionado, sem descontar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .analysis import AnalysisContext, AnalysisStage
from .domain import (
    RelatedTicket,
    RelatedTicketsCheck,
    RelatedTicketsRule,
    Stage,
    Ticket,
    location_label,
)
from .formatting import brl
from .llm_schemas import RelatedTicketJudgment, RelatedTicketsReview
from .providers import ProviderError, TextPart
from .repository import LoadedTicket, QuoteError, load_ticket, read_ticket_quote
from .scope import ScopeStage

log = logging.getLogger(__name__)

# Situação do chamado (como vem do Salesforce) → português, para o prompt e a tela.
STATUS_PT = {
    "forwarded_to_backoffice": "em análise no backoffice",
    "open": "aberto",
    "in_progress": "em execução",
    "awaiting_supplier": "aguardando o fornecedor",
    "awaiting_quote": "aguardando orçamento",
    "approved": "aprovado",
    "rejected": "recusado",
    "cancelled": "cancelado",
    "closed": "encerrado",
    "completed": "concluído",
    "paid": "pago",
}

MAX_ITEMS_IN_PROMPT = 12  # itens do orçamento de cada chamado enviados ao modelo
# Abertos até N dias antes ou depois entram na frente mesmo com outra categoria: um duplicado costuma vir logo em
# seguida, e quem abre escolhe a categoria de outro jeito (goteira × forro manchado).
CLOSE_DAYS = 7


def status_label(status: str) -> str:
    return STATUS_PT.get(status, status.replace("_", " "))


@dataclass
class PoolEntry:
    """Chamado da base (atuais ou histórico) que pode entrar na comparação."""

    ticket: LoadedTicket
    source: str  # "tickets" | "history"


@dataclass
class Candidate:
    """Chamado da mesma agência que entrou na comparação, com a distância em dias e o motivo de entrar."""

    entry: PoolEntry
    days_apart: int  # positivo = aberto antes do chamado em análise
    in_window: bool

    @property
    def data(self) -> Ticket:
        return self.entry.ticket.data


def find_candidates(
    current: Ticket,
    pool: list[PoolEntry],
    rule: RelatedTicketsRule,
    skip_datasets: list[str] | None = None,
) -> list[Candidate]:
    """Chamados da mesma agência dentro dos critérios da régua, dos mais próximos para os mais distantes.

    Args:
        current: chamado em análise.
        pool: chamados atuais e do histórico.
        rule: [rubric.related_tickets] (janela, ainda abertos, situações encerradas).
        skip_datasets: conjuntos que ficam fora da comparação ([pipeline] related_skip_datasets).

    Returns:
        Todos os que entram (o limite `max_candidates` é aplicado por quem chama): primeiro os da mesma categoria
        ou abertos até CLOSE_DAYS dias antes/depois; depois os demais; em cada grupo, da abertura mais próxima
        para a mais distante.
    """
    skip = set(skip_datasets or ())
    out: list[Candidate] = []
    for e in pool:
        other = e.ticket.data
        if other.ticket_id == current.ticket_id or other.dataset in skip:
            continue
        if not current.branch.same_as(other.branch):
            continue
        days = (current.dates.opening - other.dates.opening).days
        in_window = abs(days) <= rule.window_days
        still_open = (
            rule.include_still_open
            and rule.is_open(other.status)
            and days > rule.window_days
        )
        if in_window or still_open:
            out.append(Candidate(e, days, in_window))
    out.sort(
        key=lambda c: (
            c.data.category != current.category and abs(c.days_apart) > CLOSE_DAYS,
            abs(c.days_apart),
        )
    )
    return out


def quote_lines(ticket: LoadedTicket) -> list[str]:
    """Itens do orçamento do chamado, para comparar o que cada um cobra (vazio sem planilha legível)."""
    if not ticket.spreadsheets:
        return []
    try:
        quote = read_ticket_quote(ticket)
    except (QuoteError, OSError, ValueError) as e:
        log.info("orçamento de %s não lido na comparação: %s", ticket.id, e)
        return []
    lines = [
        f"{i.n}. {i.description} ({i.quantity:g} {i.unit})"
        for i in quote.items[:MAX_ITEMS_IN_PROMPT]
    ]
    if len(quote.items) > MAX_ITEMS_IN_PROMPT:
        lines.append(f"(+{len(quote.items) - MAX_ITEMS_IN_PROMPT} itens)")
    return lines


def describe(c: Candidate) -> str:
    """Bloco de um chamado da agência no prompt."""
    d = c.data
    when = (
        "aberto no mesmo dia"
        if c.days_apart == 0
        else (
            f"aberto {c.days_apart} dia(s) antes deste"
            if c.days_apart > 0
            else f"aberto {-c.days_apart} dia(s) depois deste"
        )
    )
    items = quote_lines(c.entry.ticket)
    return (
        f"--- Chamado {d.ticket_id} | aberto em {d.dates.opening:%d/%m/%Y} ({when}) | situação: {status_label(d.status)}\n"
        f"Esteira {d.workstream.value} | Categoria: {d.category.label} | Sintoma: {d.symptom.label} | "
        f"Momento: {'aprovação do orçamento' if d.moment.value == 'quote' else 'atestação do serviço'}\n"
        f"Local do chamado: {location_label(d.branch.environment) or 'não informado'} | Fornecedor: {d.supplier.name}"
        + (f" | Valor orçado: {brl(d.quoted_value)}" if d.quoted_value else "")
        + f"\nESCOPO: {d.requested_scope}"
        + (
            f"\nSOLUÇÃO: {d.solution_description.strip()}"
            if d.solution_description.strip()
            else ""
        )
        + (
            "\nITENS DO ORÇAMENTO:\n" + "\n".join(f"  {x}" for x in items)
            if items
            else ""
        )
    )


class RelatedTicketsStage(AnalysisStage):
    """Compara o chamado com os outros chamados da mesma agência e aponta possível duplicidade."""

    name = "related"
    progress = Stage.RELATED

    def __init__(self, *args, pool: list[PoolEntry] | None = None, **kwargs):
        """
        Args:
            *args, **kwargs: os de `AnalysisStage` (cfg, references, scorer).
            pool: chamados de onde sair a comparação; None lê as pastas de chamados e do histórico na primeira vez.
        """
        super().__init__(*args, **kwargs)
        self._pool = pool

    def pool(self) -> list[PoolEntry]:
        """Chamados atuais e do histórico (lidos uma vez por orquestrador, ou seja, por execução)."""
        if self._pool is None:
            entries: list[PoolEntry] = []
            for folder, source in (
                (self.cfg.tickets_dir, "tickets"),
                (self.cfg.history_dir, "history"),
            ):
                if not Path(folder).exists():
                    continue
                for p in sorted(Path(folder).iterdir()):
                    if not (p / "ticket.json").exists():
                        continue
                    try:
                        entries.append(PoolEntry(load_ticket(p), source))
                    except (
                        OSError,
                        ValueError,
                    ) as e:  # chamado ilegível não derruba a análise dos outros
                        log.warning("chamado %s ignorado na comparação: %s", p.name, e)
            self._pool = entries
        return self._pool

    def run(self, ctx: AnalysisContext) -> None:
        """Preenche `ctx.related` e, para cada chamado com chance alta de ser o mesmo problema, acrescenta o
        apontamento `possible_duplicate_ticket`.

        Os argumentos passados ao session.ask:
            task: "related_tickets" (prompt de sistema em config/prompts.toml).
            parts: o chamado em análise (resumo, leitura do escopo, itens) e os chamados da agência, em texto.
            output: `RelatedTicketsReview` (um julgamento por chamado: relação, chance, coincidências e diferenças).
            fast: True (só texto); max_tokens: proporcional à quantidade de chamados.
            meta: ids dos chamados comparados (o modo simulado usa).
        """
        rule = self.rubric.related_tickets
        ticket = ctx.ticket.data
        check = RelatedTicketsCheck(
            window_days=rule.window_days,
            include_still_open=rule.include_still_open,
            min_probability=rule.min_probability,
            show_probability=rule.show_probability,
        )
        ctx.related = check
        skip = self.cfg.pipeline.related_skip_datasets
        if not rule.enabled:
            check.skipped = "comparação com chamados da agência desativada na régua"
            return
        if ticket.dataset in skip:
            check.skipped = f"o conjunto {ticket.dataset} fica fora da comparação (agência e data sorteadas pelo gerador)"
            return

        found = find_candidates(ticket, self.pool(), rule, skip)
        check.candidates_found = len(found)
        candidates = found[: rule.max_candidates]
        if not candidates:
            return

        current_items = quote_lines(ctx.ticket)
        text = "CHAMADO EM ANÁLISE\n" + ticket.summary_text() + (
            f"\nLEITURA DO ESCOPO:\n{ScopeStage.describe(ctx.scope)}"
            if ctx.scope
            else ""
        ) + (
            "\nITENS DO ORÇAMENTO:\n" + "\n".join(f"  {x}" for x in current_items)
            if current_items
            else ""
        ) + f"\n\nCHAMADOS DA MESMA AGÊNCIA ({len(candidates)}), abertos até {rule.window_days} dia(s) antes ou " "depois deste" + (
            " ou que seguem abertos" if rule.include_still_open else ""
        ) + ":\n" + "\n\n".join(
            describe(c) for c in candidates
        )
        try:
            review = ctx.session.ask(
                "related_tickets",
                [TextPart(text)],
                RelatedTicketsReview,
                fast=True,
                max_tokens=min(8000, 600 + 450 * len(candidates)),
                meta={"candidates": [c.data.ticket_id for c in candidates]},
            )
        except ProviderError as e:
            log.warning("comparação com chamados da agência falhou: %s", e)
            check.skipped = (
                "o modelo não respondeu à comparação com os chamados da agência"
            )
            check.tickets = [self._related(c, None, rule) for c in candidates]
            ctx.confidence_reducers.append("related_not_checked")
            return

        by_id = {j.ticket_id.strip(): j for j in review.judgments}
        related = [
            self._related(c, by_id.get(c.data.ticket_id), rule) for c in candidates
        ]
        related.sort(key=lambda r: (-r.probability, abs(r.days_apart)))
        check.tickets = related
        for r in related:
            if r.flagged:
                ctx.findings.append(
                    self.scorer.finding(
                        "possible_duplicate_ticket",
                        f"Chamado {r.ticket_id} da mesma agência, aberto em {r.opening:%d/%m/%Y} "
                        f"({status_label(r.status)}): {r.probability}% de chance de ser o mesmo problema. {r.reason}",
                        f"chamado {r.ticket_id}",
                    )
                )

    @staticmethod
    def _related(
        c: Candidate, j: RelatedTicketJudgment | None, rule: RelatedTicketsRule
    ) -> RelatedTicket:
        d = c.data
        probability = j.probability if j else 0
        return RelatedTicket(
            ticket_id=d.ticket_id,
            source=c.entry.source,
            opening=d.dates.opening,
            status=d.status,
            is_open=rule.is_open(d.status),
            category=d.category.value,
            category_label=d.category.label,
            symptom_label=d.symptom.label,
            environment=d.branch.environment,
            scope=d.requested_scope,
            supplier=d.supplier.name,
            quoted_value=d.quoted_value,
            days_apart=c.days_apart,
            in_window=c.in_window,
            probability=probability,
            relation=j.relation if j else "different",
            reason=j.reason if j else "O modelo não comparou este chamado.",
            matching_points=list(j.matching_points) if j else [],
            differences=list(j.differences) if j else [],
            flagged=bool(j) and probability >= rule.min_probability,
        )
