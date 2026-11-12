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
    "lpu": "lpu",
    "item lpu": "lpu",
    "é lpu": "lpu",
    "e lpu": "lpu",
}
LPU_TRUE = {"sim", "s", "true", "verdadeiro", "x", "1", "lpu"}
LPU_FALSE = {"não", "nao", "n", "false", "falso", "0", "não lpu", "nao lpu"}


def _lpu_flag(value: Any, n: int) -> bool:
    """Coluna LPU: Sim/Não (ou caixa de seleção do Excel, x, 1/0). Vazio é tratado antes, como Sim."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in LPU_TRUE:
        return True
    if text in LPU_FALSE:
        return False
    raise QuoteError(f"item {n}: a coluna LPU aceita Sim ou Não (encontrado '{value}')")
TICKET_FIELDS = {
    "chamado": "ticket_id",
    "nº orçamento": "number",
    "numero do orçamento": "number",
    "fornecedor": "supplier",
    "cnpj": "supplier_cnpj",
    "data": "issued_on",
    "categoria": "category",
    "sintoma": "symptom",
    "escopo": "scope",
    "descrição do problema": "scope",
    "descricao do problema": "scope",
    "descrição detalhada do problema": "scope",
}
ITEM_PLACEHOLDER = "descreva o item cobrado"  # linha de exemplo do modelo: não conta como item
NOT_ITEMS = {"total", "subtotal", "total geral", "valor total", ITEM_PLACEHOLDER}  # linhas de soma ou de exemplo


def _table_rows(ws, table_name: str) -> list[list[Any]] | None:
    """Linhas da Tabela do Excel com esse nome, ou None se a aba não tiver a tabela."""
    if table_name not in ws.tables:
        return None
    ref = ws.tables[table_name].ref
    return [[c.value for c in row] for row in ws[ref]]


def _item_header(row: list[Any]) -> list[str | None]:
    return [ITEM_COLUMNS.get(str(c or "").strip().lower()) for c in row]


def _items_rows(wb) -> list[list[Any]]:
    """Cabeçalho + linhas dos itens: a Tabela tbItens da aba 'Itens' ou, numa planilha simples, a primeira linha de
    qualquer aba que tenha as colunas dos itens (Descrição, Quantidade e Valor unitário; Item e Valor total são opcionais)."""
    sheets = [wb["Itens"]] if "Itens" in wb.sheetnames else [ws for ws in wb.worksheets if ws.title != "Chamado"]
    for ws in sheets:
        if (rows := _table_rows(ws, "tbItens")) is not None:
            return rows
        values = [list(r) for r in ws.iter_rows(values_only=True)]
        for i, row in enumerate(values[:30]):
            cols = set(_item_header(row)) - {None}
            if {"description", "quantity"} <= cols and cols & {"unit_value", "total_value"}:
                return values[i:]
    raise QuoteError(
        "não encontrei a lista de itens: use a aba 'Itens' do modelo ou uma planilha com as colunas "
        "Descrição, Unidade, Quantidade e Valor unitário"
    )


def _ticket_rows(wb) -> list[list[Any]] | None:
    """Campo | Valor da aba 'Chamado' (Tabela tbChamado ou as duas primeiras colunas), ou None sem a aba."""
    if "Chamado" not in wb.sheetnames:
        return None
    ws = wb["Chamado"]
    rows = _table_rows(ws, "tbChamado")
    return rows[1:] if rows is not None else [list(r)[:2] for r in ws.iter_rows(values_only=True)]


def quote_defaults(ticket: Ticket) -> dict[str, Any]:
    """Dados do chamado que completam a planilha: quem envia pelo painel só precisa cadastrar os itens."""
    return {
        "ticket_id": ticket.ticket_id,
        "category": ticket.category.value,
        "symptom": ticket.symptom.value,
        "scope": ticket.requested_scope,
        "supplier": ticket.supplier.name,
        "supplier_cnpj": ticket.supplier.cnpj,
        "number": "",
    }


def read_quote(path: Path, defaults: dict[str, Any] | None = None) -> Quote:
    """Lê o orçamento: aba 'Chamado' (Campo | Valor) e itens (aba 'Itens' do modelo ou planilha simples com as colunas).

    `defaults`: dados do chamado (quote_defaults) para o que a planilha não trouxer; com eles, a aba 'Chamado' é
    opcional e basta a lista de itens. Sem eles (dados de exemplo), a aba 'Chamado' é obrigatória.
    """
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as e:  # arquivo corrompido ou não-Excel
        raise QuoteError(f"não foi possível abrir {path.name}: o arquivo não é uma planilha Excel válida ou está corrompido") from e

    ticket_rows = _ticket_rows(wb)
    if ticket_rows is None and defaults is None:
        raise QuoteError("a planilha precisa das abas 'Chamado' e 'Itens'")
    ticket_fields: dict[str, Any] = {}
    for field, value, *_ in [r + [None] * (2 - len(r)) for r in ticket_rows or []]:
        key = TICKET_FIELDS.get(str(field or "").strip().lower())
        if key and value not in (None, ""):
            ticket_fields[key] = value
    for key, value in (defaults or {}).items():  # o que a planilha não trouxe vem do chamado
        ticket_fields.setdefault(key, value)
    if isinstance(ticket_fields.get("issued_on"), datetime):
        ticket_fields["issued_on"] = ticket_fields["issued_on"].date()

    rows = _items_rows(wb)
    header = _item_header(rows[0])
    if len(set(header) - {None}) != len([c for c in header if c]) or "description" not in header:
        found = ", ".join(str(c) for c in rows[0] if c is not None) or "nenhuma"
        raise QuoteError(f"colunas dos itens fora do padrão (encontradas: {found})")
    items = []
    for row in rows[1:]:
        item = {col: v for col, v in zip(header, row, strict=False) if col and v not in (None, "")}
        desc = str(item.get("description", "")).strip().lower().rstrip(":")
        if not desc or desc in NOT_ITEMS:  # sem descrição (linha de total, observação) ou linha de exemplo do modelo
            continue
        item.setdefault("n", len(items) + 1)
        item.setdefault("unit", "un")
        if "lpu" in item:  # sem a coluna (planilhas antigas) ou em branco: item da LPU
            item["lpu"] = _lpu_flag(item["lpu"], item["n"])
        if "total_value" not in item and "unit_value" in item and "quantity" in item:
            item["total_value"] = round(float(item["quantity"]) * float(item["unit_value"]), 2)
        if "unit_value" not in item and "total_value" in item and item.get("quantity"):
            item["unit_value"] = round(float(item["total_value"]) / float(item["quantity"]), 2)
        items.append(item)
    if not items:
        raise QuoteError("a planilha não tem itens: preencha ao menos uma linha com descrição, quantidade e valor")
    try:
        return Quote(
            file=path.name,
            items=[QuoteItem.model_validate(i) for i in items],
            **{k: (str(v or "") if k in ("ticket_id", "number", "supplier_cnpj") else v) for k, v in ticket_fields.items()},
        )
    except ValidationError as e:
        raise QuoteError(f"planilha com valores inválidos: {pt_validation_error(e.errors())}") from e


def read_ticket_quote(ticket: LoadedTicket, attachment: Attachment | None = None) -> Quote:
    """Orçamento do chamado, completado com os dados do próprio chamado (planilha só com itens também vale)."""
    a = attachment or ticket.spreadsheets[0]
    return read_quote(a.path, quote_defaults(ticket.data))


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
    dataset: str = "scenarios"
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
