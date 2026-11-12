"""Modelo da planilha de orçamento (para o fornecedor preencher), gerado sob demanda pelo painel.

Só a aba 'Itens': os dados do chamado (agência, fornecedor, categoria, sintoma, descrição) vêm do formulário do
Novo chamado, e o número de cada item, o valor total de cada item e o valor do orçamento são calculados pelo Atest.AI.
Planilhas no formato antigo, com a aba 'Chamado', continuam sendo lidas (repository.read_quote).
"""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

# LPU: "Sim" se o item está na tabela de preços; "Não" se é fora da LPU (em branco conta como Sim)
ITEM_HEADER = ["Descrição", "Unidade", "LPU", "Quantidade", "Valor unitário"]
WIDTHS = (58, 10, 8, 12, 16)


def spreadsheet_template() -> bytes:
    """Planilha modelo (Excel) com a aba 'Itens' e uma linha de exemplo, que não conta como item se não for trocada."""
    wb = Workbook()
    wi = wb.active
    wi.title = "Itens"
    wi.append(ITEM_HEADER)
    wi.append(["Descreva o item cobrado", "un", "Sim", 1, 0])
    tab = Table(displayName="tbItens", ref="A1:E2")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    wi.add_table(tab)
    lpu = DataValidation(type="list", formula1='"Sim,Não"', allow_blank=True, showDropDown=False)
    lpu.prompt, lpu.promptTitle = "Sim: item da tabela de preços (LPU). Não: item fora da LPU.", "LPU"
    wi.add_data_validation(lpu)
    lpu.add("C2:C500")
    for col, w in zip("ABCDE", WIDTHS, strict=True):
        wi.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
