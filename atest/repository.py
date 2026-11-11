"""Leitura dos dados: chamados, orçamento em Excel, bases de referência e gabarito."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from pydantic import BaseModel, ConfigDict, ValidationError

from .config import ChecklistRequirement, Settings
from .domain import (
    Attachment,
    LpuItem,
    Quote,
    QuoteItem,
    Recommendation,
    Rubric,
    Ticket,
)
from .formatting import pt_validation_error

log = logging.getLogger(__name__)


class QuoteError(ValueError):
    """Planilha fora do padrão (abas/tabelas/colunas) ou com valores inválidos."""


# ============================================================================ chamado
class LoadedTicket(BaseModel):
    """Chamado + pasta + anexos numerados."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: Ticket
    folder: Path
    attachments: list[Attachment]

    @property
    def id(self) -> str:
        return self.data.ticket_id

    def attachment(self, name: str) -> Attachment | None:
        """Anexo pelo número (como no rótulo 'Anexo N')."""
        return next((a for a in self.attachments if a.name == name), None)

    @property
    def spreadsheets(self) -> list[Attachment]:
        """Anexos que são planilhas Excel."""
        return [a for a in self.attachments if a.is_spreadsheet]


def load_ticket(folder: Path) -> LoadedTicket:
    """Lê ticket.json e lista os anexos da pasta do chamado."""
    folder = Path(folder)
    data = Ticket.model_validate_json((folder / "ticket.json").read_text(encoding="utf-8"))
    attachments = [
        Attachment(index=i, path=folder / "attachments" / a.file_name, content_type=a.content_type) for i, a in enumerate(data.attachments, 1)
    ]
    return LoadedTicket(data=data, folder=folder, attachments=attachments)


def list_tickets(tickets_dir: Path, ids: list[str] | None = None) -> list[Path]:
    """Pastas de chamados (opcionalmente só os ids pedidos), em ordem."""
    folders = sorted(p for p in Path(tickets_dir).iterdir() if (p / "ticket.json").exists())
    return [p for p in folders if p.name in ids] if ids else folders


# ============================================================================ orçamento (Excel)
# Rótulos da planilha (contrato com quem preenche, em português) → campos do modelo Quote.
ITEM_COLUMNS = {
    "item": "n",
    "descrição": "description",
    "descricao": "description",
    "unidade": "unit",
    "quantidade": "quantity",
    "valor unitário": "unit_value",
    "valor unitario": "unit_value",
    "valor total": "total_value",
}
TICKET_FIELDS = {
    "chamado": "ticket_id",
    "nº orçamento": "number",
    "numero do orçamento": "number",
    "fornecedor": "supplier",
    "data": "issued_on",
    "categoria": "category",
    "sintoma": "symptom",
    "escopo": "scope",
}


def _table_rows(ws, table_name: str) -> list[list[Any]]:
    if table_name not in ws.tables:
        raise QuoteError(f"aba '{ws.title}' sem a tabela '{table_name}'")
    ref = ws.tables[table_name].ref
    return [[c.value for c in row] for row in ws[ref]]


def read_quote(path: Path) -> Quote:
    """Lê a planilha padrão: aba 'Chamado' (tabela tbChamado: Campo | Valor) e aba 'Itens' (tabela tbItens)."""
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as e:  # arquivo corrompido ou não-Excel
        raise QuoteError(f"não foi possível abrir {path.name}: o arquivo não é uma planilha Excel válida ou está corrompido") from e
    if "Chamado" not in wb.sheetnames or "Itens" not in wb.sheetnames:
        raise QuoteError("a planilha precisa das abas 'Chamado' e 'Itens'")

    ticket_fields: dict[str, Any] = {}
    for field, value, *_ in _table_rows(wb["Chamado"], "tbChamado")[1:]:
        key = TICKET_FIELDS.get(str(field or "").strip().lower())
        if key:
            ticket_fields[key] = value
    if isinstance(ticket_fields.get("issued_on"), datetime):
        ticket_fields["issued_on"] = ticket_fields["issued_on"].date()

    rows = _table_rows(wb["Itens"], "tbItens")
    columns = [ITEM_COLUMNS.get(str(c or "").strip().lower()) for c in rows[0]]
    if None in columns or len(set(columns)) != len(columns):
        found = ", ".join(str(c) for c in rows[0] if c is not None) or "nenhuma"
        raise QuoteError(f"colunas da tabela tbItens fora do padrão (encontradas: {found})")
    items = [dict(zip(columns, row, strict=True)) for row in rows[1:] if any(v is not None for v in row)]
    try:
        return Quote(
            file=path.name,
            items=[QuoteItem.model_validate(i) for i in items],
            **{k: (str(v) if k in ("ticket_id", "number") else v) for k, v in ticket_fields.items()},
        )
    except ValidationError as e:
        raise QuoteError(f"planilha com valores inválidos: {pt_validation_error(e.errors())}") from e


# ============================================================================ referências
class References:
    """Tabela de preços de referência (LPU) por esteira, lida de data/references/lpu_*.csv,
    mais régua e checklists vindos da configuração (config/*.toml)."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.dir = cfg.references_dir

    @property
    def rubric(self) -> Rubric:
        return self.cfg.rubric

    @cached_property
    def lpu(self) -> dict[str, dict[str, LpuItem]]:
        out: dict[str, dict[str, LpuItem]] = {}
        for p in sorted(self.dir.glob("lpu_*.csv")):
            workstream = p.stem.split("_", 1)[1].upper()
            with open(p, encoding="utf-8") as f:
                out[workstream] = {r["code"]: LpuItem.model_validate(r) for r in csv.DictReader(f, delimiter=";")}
        return out

    @property
    def attachment_categories(self) -> dict[str, str]:
        return self.cfg.checklists.attachment_categories

    def requirements(self, ticket: Ticket) -> list[ChecklistRequirement]:
        """Requisitos do checklist para o chamado."""
        return self.cfg.checklists.requirements(ticket.category.value, ticket.maintenance_type.value, ticket.moment.value, ticket.workstream.value)

    def lpu_text(self, workstream: str) -> str:
        """Tabela de referência da esteira em texto, para o prompt de conferência do orçamento."""
        rows = ["codigo | descricao | unidade | preco_referencia (R$)"]
        rows += [f"{r.code} | {r.description} | {r.unit} | {r.reference_price:.2f}" for r in self.lpu[workstream].values()]
        return "\n".join(rows)


# ============================================================================ gabarito
class GroundTruth(BaseModel):
    """Resposta esperada de um chamado do dataset sintético."""

    model_config = ConfigDict(extra="ignore")

    ticket_id: str
    recommendation: Recommendation
    score: int | None
    confidence: str | None
    checklist_ok: bool
    missing: list[str]
    findings: list[str]
    optional: list[str] = []
    grades: dict[str, int] | None = None
    maintenance_type: str
    moment: str = "execution"
    before_applicable: bool = True
    dataset: str = "demo"
    service_template: str | None = None
    defects: list[str] = []
    amount_at_issue: float | None = None
    items: list[dict[str, Any]]
    attachments: dict[str, dict[str, Any]]
    scenario: dict[str, str] | None = None  # catálogo de cenários (0300…): id, título e o que o chamado testa


def load_ground_truth(ground_truth_dir: Path, ticket_id: str) -> GroundTruth | None:
    """Gabarito do chamado, se existir."""
    p = Path(ground_truth_dir) / f"{ticket_id}.json"
    return GroundTruth.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None
