"""Modelo da planilha padrão de orçamento (para o fornecedor preencher), gerado sob demanda pelo painel."""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from .domain import current_catalog

FIELDS = ["Chamado", "Esteira", "Agência", "Fornecedor", "CNPJ", "Nº orçamento", "Data", "Categoria", "Sintoma", "Escopo", "Valor total"]


def spreadsheet_template(
    ticket_id: str = "", category: str = "", symptom: str = "", scope: str = "",
    categories: list[str] | None = None, symptoms: list[str] | None = None,
) -> bytes:
    """Planilha modelo (Excel) já preenchida com categoria, sintoma e escopo, para o fornecedor completar.

    `categories` e `symptoms`: códigos oferecidos na lista de escolha das células (padrão: os ativos do cadastro).
    """
    catalog = current_catalog()
    categories = categories if categories is not None else catalog.codes("categories", enabled_only=True)
    symptoms = symptoms if symptoms is not None else catalog.codes("symptoms", enabled_only=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Chamado"
    filled = {"Chamado": ticket_id, "Categoria": category, "Sintoma": symptom, "Escopo": scope}
    ws.append(["Campo", "Valor"])
    for c in FIELDS:
        ws.append([c, filled.get(c, "")])
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 90
    ws["B11"].alignment = Alignment(wrap_text=True, vertical="top")
    tab = Table(displayName="tbChamado", ref=f"A1:B{len(FIELDS) + 1}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(tab)
    for cell, values in (("B9", categories), ("B10", symptoms)):
        if len(",".join(values)) > 250:  # o Excel limita a lista direta a 255 caracteres: sem lista, a célula fica livre
            continue
        dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(cell)

    wi = wb.create_sheet("Itens")
    wi.append(["Item", "Descrição", "Unidade", "Quantidade", "Valor unitário", "Valor total"])
    wi.append([1, "Descreva o item cobrado", "un", 1, 0, 0])
    tab = Table(displayName="tbItens", ref="A1:F2")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    wi.add_table(tab)
    for col, w in zip("ABCDEF", (7, 58, 10, 12, 16, 16), strict=True):
        wi.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
