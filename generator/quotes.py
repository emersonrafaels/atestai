"""Gera o orçamento padrão em Excel (formato Tabela) de cada chamado.

Aba "Chamado"  → tabela tbChamado (Campo | Valor): chamado, fornecedor, nº, data, categoria, sintoma, escopo, total
Aba "Itens"    → tabela tbItens (Item | Descrição | Unidade | Quantidade | Valor unitário | Valor total)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from cases import SUPPLIER
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.table import Table, TableStyleInfo


def total(case: dict) -> float:
    return round(sum(q * u for _, _, q, u, _ in case["items"]), 2)


def make_xlsx(path: Path, case: dict) -> None:
    name, cnpj, _ = SUPPLIER[case["supplier"]]
    code, branch_name, environment = case["branch"]
    wb = Workbook()

    ws = wb.active
    ws.title = "Chamado"
    fields = [
        ("Campo", "Valor"),
        ("Chamado", case["id"]),
        ("Esteira", case["workstream"]),
        ("Agência", f"{branch_name} ({code}) — {environment}"),
        ("Fornecedor", name),
        ("CNPJ", cnpj),
        ("Nº orçamento", case["quote_number"]),
        ("Data", date.fromisoformat(case["dates"]["supplier_submission"])),
        ("Categoria", case.get("spreadsheet", {}).get("category", case["category"])),
        ("Sintoma", case.get("spreadsheet", {}).get("symptom", case["symptom"])),
        ("Escopo", case["scope"]),
        ("Valor total", total(case)),
    ]
    for row in fields:
        ws.append(row)
    ws["B8"].number_format = "dd/mm/yyyy"
    ws["B12"].number_format = "R$ #,##0.00"
    ws["B11"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 90
    tab = Table(displayName="tbChamado", ref=f"A1:B{len(fields)}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(tab)

    wi = wb.create_sheet("Itens")
    wi.append(["Item", "Descrição", "Unidade", "Quantidade", "Valor unitário", "Valor total"])
    for n, (desc, un, q, u, _) in enumerate(case["items"], 1):
        wi.append([n, desc, un, q, u, round(q * u, 2)])
    end = len(case["items"]) + 1
    for r in range(2, end + 1):
        wi.cell(r, 5).number_format = "R$ #,##0.00##"
        wi.cell(r, 6).number_format = "R$ #,##0.00"
    tab = Table(displayName="tbItens", ref=f"A1:F{end}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    wi.add_table(tab)
    wi.cell(end + 2, 5, "Total").font = Font(bold=True)
    c = wi.cell(end + 2, 6, total(case))
    c.font = Font(bold=True)
    c.number_format = "R$ #,##0.00"
    for col, w in zip("ABCDEF", (7, 58, 10, 12, 16, 16), strict=True):
        wi.column_dimensions[col].width = w
    wb.save(path)
