"""Gera os casos fictícios do conjunto "Casos Itaú - Salesforce" (dataset `casos`) que testam chamados da mesma agência
e reaproveitamento de foto.

Cada caso vira data/tickets/<id>/ com ticket.json (formato da extração do Salesforce), a planilha de orçamento (só a aba
Itens, como o fornecedor envia), as fotos e um LEIAME.txt com o que o parecer deveria apontar. Os casos `casos` não têm
gabarito: rodam no modo API.

Fotos (todas SIMULADAS):
- recorte de um ângulo diferente de imagens geradas por IA da biblioteca data/real_photos_itau/ (fora do git; veja
  generator/ai_photos.py), com outro enquadramento, brilho e data no EXIF;
- nos casos de reaproveitamento, cópia recortada e recomprimida de uma foto de outro chamado, com data nova no EXIF.

No fim, o gerador confere com o mesmo índice de hashes do pipeline (`PhotoIndex`) que só as fotos reaproveitadas de
propósito parecem com fotos de outros chamados. Se outra foto bater, ele avisa e sai com erro: troque o recorte.

    python generator/build_salesforce_cases.py           # gera os casos que ainda não existem
    python generator/build_salesforce_cases.py --force   # regera (sobrescreve) os casos desta lista
    python generator/build_salesforce_cases.py --check   # só a conferência de semelhança das fotos
"""

from __future__ import annotations

import argparse
import io
import json
import random
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import piexif
from openpyxl import Workbook
from openpyxl.worksheet.table import Table, TableStyleInfo
from PIL import Image, ImageEnhance

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from atest.attachments import compute_hashes, detail_level, distance  # noqa: E402
from atest.config import load_settings  # noqa: E402
from atest.photos import PhotoIndex  # noqa: E402
from atest.repository import load_ticket  # noqa: E402
from pdf_report import Question, render_report  # noqa: E402
from atest.spreadsheet import ITEM_HEADER, WIDTHS  # noqa: E402

TICKETS = ROOT / "data" / "tickets"
LIBRARY = ROOT / "data" / "real_photos_itau"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_SIDE = 1536


@dataclass
class Photo:
    """Foto do caso: recorte de uma imagem de origem (biblioteca ou outro chamado)."""

    name: str  # IMG_AAAAMMDD_HHMMSS.jpg: a data e a hora vão também para o EXIF
    source: str  # relativo a data/ (ex.: "real_photos_itau/ceiling_view/x.jpg" ou "tickets/04159084/attachments/y.jpg")
    crop: tuple[float, float, float, float]  # frações (esquerda, topo, direita, base)
    description: str  # vai no EXIF (ImageDescription)
    reused_from: str = (
        ""  # "chamado/arquivo" quando é reaproveitamento plantado de propósito
    )
    quality: int = 88

    @property
    def taken_at(self) -> datetime:
        return datetime.strptime(self.name[4:19], "%Y%m%d_%H%M%S")


@dataclass
class Case:
    ticket_id: str
    workstream: str
    category: str
    symptom: str
    scope: str
    solution: str
    branch: dict[str, str]
    supplier: str
    opening: str
    submission: str
    quote_file: str
    items: list[
        tuple[str, str, bool, float, float]
    ]  # descrição, unidade, LPU, quantidade, valor unitário
    photos: list[Photo]
    readme: str
    status: str = "forwarded_to_backoffice"
    moment: str = "quote"
    maintenance_type: str = "corrective"
    blocks_opening: bool = False
    extra: dict = field(default_factory=dict)
    report: Report | None = (
        None  # relatório em PDF (formato checklist da SISR), com as fotos dentro dele
    )


@dataclass
class ReportItem:
    """Pergunta do relatório em PDF: resposta marcada (True = Sim, False = Não, None = N/A) e a foto que a demonstra."""

    text: str
    answer: bool | None
    photo: Photo | None = None
    note: str = ""


@dataclass
class Report:
    """Relatório de atendimento em PDF no formato checklist da SISR (as fotos vão DENTRO do PDF, não soltas)."""

    file: str
    title: str
    header: list[str]
    items: list[ReportItem]
    footer: list[str] = field(default_factory=list)

    @property
    def photos(self) -> list[Photo]:
        return [q.photo for q in self.items if q.photo]


HEADER = (
    "CASO FICTÍCIO criado para testar o Atest.AI (não é um chamado real do Salesforce): agência, fornecedor, valores e\n"
    "problemas foram inventados. As imagens em attachments/ são SIMULADAS ({origin}); não são evidência real.\n"
    "A origem também está no EXIF (ImageDescription) de cada imagem. Gerado por generator/build_salesforce_cases.py.\n\n"
)
LIB_ORIGIN = "recortes de imagens geradas por IA da biblioteca data/real_photos_itau, OpenAI gpt-image"

CAMPINAS = {"code": "1520", "name": "Campinas Cambuí"}

CASES: list[Case] = [
    # ------------------------------------------------------------------ Campinas Cambuí (1520): chamados da mesma agência
    Case(
        ticket_id="04161377",
        workstream="SETA",
        category="air_conditioning",
        symptom="leak",
        scope=(
            "Ar-condicionado split do autoatendimento pingando água na parede e no forro ao lado dos caixas "
            "eletrônicos. É o aparelho do lado direito de quem entra."
        ),
        solution="Limpeza completa do split, desobstrução do dreno e troca da mangueira de drenagem.",
        branch={**CAMPINAS, "environment": "area_interna_publico"},
        supplier="Climafrio Refrigeração LTDA",
        opening="2026-10-22",
        submission="2026-10-23",
        status="awaiting_supplier",
        quote_file="Orcamento_Climafrio_04161377.xlsx",
        items=[
            (
                "Limpeza preventiva de split até 24.000 BTU (evaporadora + condensadora)",
                "un",
                True,
                1,
                180.00,
            ),
            ("Higienização com bactericida", "un", True, 1, 45.00),
            (
                "Desobstrução do dreno e troca da mangueira de drenagem (3 m)",
                "vb",
                False,
                1,
                210.00,
            ),
            ("Visita técnica e deslocamento", "vb", True, 1, 150.00),
        ],
        photos=[
            Photo(
                "IMG_20261022_101230.jpg",
                "real_photos_itau/split_evaporator/ia_openai_1794211870_00.jpg",
                (0.0, 0.0, 0.72, 0.78),
                "split do autoatendimento pingando",
            ),
            Photo(
                "IMG_20261022_101512.jpg",
                "real_photos_itau/split_evaporator/ia_openai_1794211870_01.jpg",
                (0.18, 0.04, 0.92, 0.74),
                "split do autoatendimento, vista de perto",
            ),
        ],
        readme=(
            "Chamado 04161377 - Ar-condicionado do autoatendimento pingando (aprovação do orçamento).\n"
            "Situação: aguardando o fornecedor (SEGUE ABERTO). Aberto em 22/10, dentro da janela de 60 dias dos chamados\n"
            "de novembro desta agência (e ainda aberto): entra na comparação deles.\n\n"
            "O que o parecer deveria apontar: nada (orçamento coerente com o escopo, preços da LPU). Na comparação feita\n"
            "pelos chamados 04174102 e 04174388 (forro manchado no mesmo autoatendimento), este deve aparecer como\n"
            "RELACIONADO (a água do split pode ser a origem da mancha), com chance intermediária, sem virar duplicidade.\n"
        ),
    ),
    Case(
        ticket_id="04174102",
        workstream="SETA",
        category="civil",
        symptom="forro_danificado",
        scope=(
            "Forro do autoatendimento com manchas de umidade e placas estufadas em cima dos caixas eletrônicos 3 e 4. "
            "Quando chove pinga água no piso perto dos caixas. Verificar a origem da água e trocar as placas danificadas."
        ),
        solution=(
            "Tratamento da infiltração na laje sobre o autoatendimento com manta líquida (12 m²), troca das placas de "
            "forro danificadas (6 m²) e pintura do forro recomposto."
        ),
        branch={**CAMPINAS, "environment": "area_interna_publico"},
        supplier="Construtora Alvorada Serviços LTDA",
        opening="2026-11-09",
        submission="2026-11-10",
        quote_file="Orcamento_Alvorada_04174102.xlsx",
        items=[
            (
                "Tratamento de infiltração com manta líquida na laje",
                "m²",
                True,
                12,
                68.00,
            ),
            (
                "Recomposição de forro de gesso (recorte e reposição)",
                "m²",
                True,
                6,
                95.00,
            ),
            ("Pintura de teto/forro em látex, 2 demãos", "m²", True, 6, 35.00),
            ("Visita técnica e deslocamento", "vb", True, 1, 150.00),
        ],
        photos=[
            Photo(
                "IMG_20261109_143010.jpg",
                "real_photos_itau/ceiling_view__stains/ia_openai_1794211448_00.jpg",
                (0.0, 0.0, 0.78, 0.8),
                "forro do autoatendimento com manchas de umidade",
            ),
            Photo(
                "IMG_20261109_143255.jpg",
                "real_photos_itau/ceiling_view__stains/ia_openai_1794297247_00.jpg",
                (0.22, 0.0, 1.0, 0.74),
                "placas do forro estufadas, vista de perto",
            ),
        ],
        readme=(
            "Chamado 04174102 - Forro do autoatendimento manchado e pingando (aprovação do orçamento).\n"
            "Agência informada com NOME E CÓDIGO (1520).\n\n"
            "Chamados da mesma agência que entram na comparação (janela de 60 dias + os que seguem abertos):\n"
            "- 04174388 (aberto 3 dias DEPOIS, só com o código 1520): goteira no teto da sala dos caixas eletrônicos, ao\n"
            "  lado do ATM 4 -> MESMO PROBLEMA, outro fornecedor e outra categoria/sintoma -> possible_duplicate_ticket.\n"
            "- 04161377 (aberto em 22/10, segue aberto): split pingando no autoatendimento -> RELACIONADO (pode ser a origem\n"
            "  da água), chance intermediária, sem apontamento.\n"
            "- 04172318 (4 dias antes): porta giratória travando -> outro problema.\n"
            "- 04174415 (4 dias depois, só com o NOME da agência): tomada queimada no backoffice -> outro problema.\n"
            "O que o parecer deveria apontar: possível chamado duplicado (04174388) -> ANÁLISE DETALHADA.\n"
            "O orçamento em si é coerente (preços da LPU).\n"
        ),
    ),
    Case(
        ticket_id="04174388",
        workstream="SETA",
        category="civil",
        symptom="moisture_infiltration",
        scope=(
            "GOTEIRA NO TETO DA SALA DOS CAIXAS ELETRONICOS, DO LADO DO ATM 4. PLACAS DO FORRO MANCHADAS E UMA QUASE "
            "CAINDO. RISCO PARA OS CLIENTES, FAVOR ATENDER RAPIDO"
        ),
        solution="Troca de 8 placas de forro e impermeabilização do ponto de infiltração.",
        branch={"code": "1520", "name": "", "environment": "area_interna_publico"},
        supplier="Reforma Já Engenharia LTDA",
        opening="2026-11-12",
        submission="2026-11-13",
        quote_file="Orcamento_ReformaJa_04174388.xlsx",
        items=[
            (
                "Impermeabilização do ponto de infiltração (manta líquida)",
                "m²",
                True,
                10,
                72.00,
            ),
            ("Troca de placas de forro de gesso", "m²", True, 5, 95.00),
            ("Fundo preparador antimofo", "m²", True, 5, 6.50),
            ("Visita técnica e deslocamento", "vb", True, 1, 150.00),
        ],
        photos=[
            Photo(
                "IMG_20261112_090145.jpg",
                "real_photos_itau/ceiling_view__stains/ia_openai_1794211448_01.jpg",
                (0.12, 0.0, 0.9, 0.7),
                "teto da sala dos caixas eletrônicos com goteira",
            ),
            Photo(
                "IMG_20261112_090322.jpg",
                "real_photos_itau/ceiling_view__stains/ia_openai_1794297247_01.jpg",
                (0.0, 0.12, 0.74, 0.92),
                "placas do forro manchadas ao lado do caixa",
            ),
        ],
        readme=(
            "Chamado 04174388 - Goteira no teto da sala dos caixas eletrônicos (aprovação do orçamento).\n"
            "Agência informada SÓ COM O CÓDIGO (1520), sem o nome: a comparação usa o código.\n\n"
            "Chamados da mesma agência que entram na comparação:\n"
            "- 04174102 (aberto 3 dias ANTES, outro fornecedor, categoria Civil / Forro danificado): forro do\n"
            "  autoatendimento manchado e pingando sobre os caixas 3 e 4 -> MESMO PROBLEMA -> possible_duplicate_ticket.\n"
            "- 04172318 (7 dias antes, fora da janela, mas segue aberto): porta giratória -> outro problema.\n"
            "- 04161377 (aberto em 22/10, segue aberto): split pingando -> relacionado, sem apontamento.\n"
            "- 04174415 NÃO entra: foi aberto só com o nome da agência, e este só tem o código (não há como saber que é a\n"
            "  mesma agência).\n"
            "O que o parecer deveria apontar: possível chamado duplicado (04174102) -> ANÁLISE DETALHADA.\n"
        ),
    ),
    Case(
        ticket_id="04174415",
        workstream="SETA",
        category="electrical",
        symptom="tomada_danificada",
        scope=(
            "Tomada da estação de trabalho 4 do backoffice queimada, com marca preta e cheiro de queimado. A tomada do "
            "lado também está esquentando."
        ),
        solution="Troca das 2 tomadas e verificação do circuito e do disjuntor.",
        branch={
            "code": "",
            "name": "Ag. Campinas - Cambuí",
            "environment": "area_interna_backoffice",
        },
        supplier="Volt Instalações Elétricas LTDA",
        opening="2026-11-13",
        submission="2026-11-14",
        quote_file="Orcamento_Volt_04174415.xlsx",
        items=[
            ("Tomada 2P+T 10 A com placa", "un", True, 2, 28.00),
            ("Mão de obra de substituição de tomada", "un", True, 2, 35.00),
            (
                "Verificação do circuito com medição de isolamento",
                "vb",
                False,
                1,
                120.00,
            ),
            ("Visita técnica e deslocamento", "vb", True, 1, 150.00),
        ],
        photos=[
            Photo(
                "IMG_20261113_110418.jpg",
                "real_photos_itau/outlets__burned/ia_openai_1794297398_00.jpg",
                (0.1, 0.08, 0.82, 0.92),
                "tomada queimada da estação 4",
            ),
            Photo(
                "IMG_20261113_110602.jpg",
                "real_photos_itau/outlets__burned/ia_openai_1794297398_02.jpg",
                (0.16, 0.0, 0.9, 0.84),
                "tomada vizinha com marca de aquecimento",
            ),
        ],
        readme=(
            "Chamado 04174415 - Tomada queimada no backoffice (aprovação do orçamento).\n"
            'Agência informada SÓ COM O NOME ("Ag. Campinas - Cambuí"), sem o código: a comparação usa o nome\n'
            'normalizado (sem "Ag.", acentos e pontuação), que bate com "Campinas Cambuí".\n\n'
            "Chamados da mesma agência que entram na comparação: 04174102 (forro, 4 dias antes), 04172318 (porta giratória,\n"
            "segue aberta) e 04161377 (split, segue aberto) -> todos OUTROS PROBLEMAS (chance baixa). O 04174388 não entra\n"
            "(só tem o código).\n"
            "O que o parecer deveria apontar: nada de duplicidade; o orçamento é coerente (LPU) -> aprovar.\n"
        ),
    ),
    # ------------------------------------------------------------------ foto reaproveitada: mesmo fornecedor, outra agência
    Case(
        ticket_id="04174630",
        workstream="SETA",
        category="electrical",
        symptom="pecas_e_equipamentos_diversos",
        scope=(
            "Quadro de distribuição de energia do salão de atendimento com fiação exposta e emaranhada, a porta do "
            "quadro não fecha. Risco de choque e de curto."
        ),
        solution="Instalação de chapa de acrílico para proteção do quadro e organização da fiação.",
        branch={
            "code": "2754",
            "name": "Duque de Caxias Centro",
            "environment": "area_interna_publico",
        },
        supplier="ATM Engenharia LTDA",
        opening="2026-11-10",
        submission="2026-11-11",
        quote_file="Orcamento_ATM_04174630.xlsx",
        items=[
            (
                "Chapa de acrílico 4 mm cortada sob medida para proteção do quadro",
                "un",
                False,
                1,
                465.00,
            ),
            (
                "Organização e identificação dos circuitos do quadro",
                "vb",
                False,
                1,
                380.00,
            ),
            ("Visita técnica e deslocamento", "vb", True, 1, 150.00),
        ],
        photos=[
            Photo(
                "IMG_20261110_151730.jpg",
                "real_photos_itau/backoffice/ia_openai_1794211003_00.jpg",
                (0.0, 0.1, 0.68, 0.9),
                "ambiente onde fica o quadro de energia",
            ),
            Photo(
                "IMG_20261110_152044.jpg",
                "tickets/04159084/attachments/IMG_20261020_094512.jpg",
                (0.04, 0.04, 0.96, 0.96),
                "COPIA RECORTADA da foto IMG_20261020_094512.jpg do chamado 04159084 (reaproveitamento plantado de "
                "proposito)",
                reused_from="04159084/IMG_20261020_094512.jpg",
                quality=82,
            ),
        ],
        readme=(
            "Chamado 04174630 - Quadro de energia com fiação exposta (aprovação do orçamento).\n\n"
            "Problemas plantados (o que o parecer deveria apontar):\n"
            "- FOTO REAPROVEITADA: IMG_20261110_152044.jpg é cópia recortada (4% das bordas) e recomprimida, com data nova\n"
            "  no EXIF, da foto IMG_20261020_094512.jpg do chamado 04159084 (agência 7942 - Rio da Pedra de Guaratiba,\n"
            "  outubro). É o MESMO FORNECEDOR (ATM Engenharia) em OUTRA AGÊNCIA -> reused_photo -> TRAVA (devolver).\n"
            'Na tela, "Comparar" na foto mostra as duas fotos lado a lado, com agência, fornecedor e datas.\n'
            "Não há outro chamado da agência 2754 na base: a comparação com chamados da agência não acha candidatos.\n"
        ),
    ),
    # ------------------------------------------------------------------ duplicado + foto reaproveitada (Guapimirim, 7856)
    Case(
        ticket_id="04174851",
        workstream="SETA",
        category="civil",
        symptom="piso_danificado",
        scope=(
            "Piso quebrado na área dos caixas eletrônicos, várias peças trincadas e soltando na frente das máquinas. "
            "Cliente já tropeçou."
        ),
        solution="Retirada das peças quebradas e assentamento de piso novo, com rejunte.",
        branch={
            "code": "7856",
            "name": "Guapimirim - RJ",
            "environment": "area_interna_publico",
        },
        supplier="Piso Forte Revestimentos LTDA",
        opening="2026-11-14",
        submission="2026-11-15",
        quote_file="Orcamento_PisoForte_04174851.xlsx",
        items=[
            ("Demolição de piso cerâmico com transporte", "m²", False, 6, 24.00),
            ("Piso cerâmico 60x60 com assentamento", "m²", False, 6, 189.00),
            ("Rejunte em cerâmica", "m²", False, 6, 13.50),
            ("Visita técnica e deslocamento", "vb", True, 1, 150.00),
        ],
        photos=[
            Photo(
                "IMG_20261114_100512.jpg",
                "tickets/04164650/attachments/IMG_20261001_150238.jpg",
                (0.03, 0.03, 0.97, 0.97),
                "COPIA RECORTADA da foto IMG_20261001_150238.jpg do chamado 04164650 (reaproveitamento plantado de "
                "proposito)",
                reused_from="04164650/IMG_20261001_150238.jpg",
                quality=80,
            ),
            Photo(
                "IMG_20261114_100733.jpg",
                "tickets/04164650/attachments/IMG_20261001_150412.jpg",
                (0.05, 0.05, 0.95, 0.95),
                "COPIA RECORTADA da foto IMG_20261001_150412.jpg do chamado 04164650 (reaproveitamento plantado de "
                "proposito)",
                reused_from="04164650/IMG_20261001_150412.jpg",
                quality=80,
            ),
        ],
        readme=(
            "Chamado 04174851 - Piso quebrado na área dos caixas eletrônicos (aprovação do orçamento).\n\n"
            "Problemas plantados (o que o parecer deveria apontar):\n"
            '- POSSÍVEL CHAMADO DUPLICADO: o chamado 04164650 (mesma agência 7856, "Substituição de piso cerâmico quebrado\n'
            '  no autoatendimento") foi aberto em 01/10, 44 dias antes, dentro da janela de 60 dias (e SEGUE ABERTO) -> entra\n'
            "  na comparação -> mesmo problema -> possible_duplicate_ticket.\n"
            "- FOTOS REAPROVEITADAS: as duas fotos são cópias recortadas e recomprimidas, com data nova no EXIF, de fotos do\n"
            "  04164650 (IMG_20261001_150238.jpg e IMG_20261001_150412.jpg), enviadas por OUTRO fornecedor -> reused_photo.\n"
            "A trava de integridade vence: DEVOLVER (trava). Os dois apontamentos aparecem no parecer.\n"
        ),
    ),
    # ------------------------------------------------------------------ outros casos
    Case(
        ticket_id="04175012",
        workstream="SISR",
        category="alarm",
        symptom="false_alarm",
        scope=(
            "Sensor de presença da tesouraria disparando sozinho de madrugada. A central registrou 5 disparos na última "
            "semana, sem ninguém na agência."
        ),
        solution="Substituição do sensor da tesouraria e teste dos demais sensores da agência.",
        branch={
            "code": "4417",
            "name": "Belo Horizonte Savassi",
            "environment": "tesouraria",
        },
        supplier="Alerta Total Sistemas de Segurança LTDA",
        opening="2026-11-12",
        submission="2026-11-13",
        quote_file="Orcamento_AlertaTotal_04175012.xlsx",
        items=[
            ("Sensor infravermelho passivo (IVP) com fio", "un", True, 3, 190.00),
            ("Mão de obra de substituição de sensor", "un", True, 3, 110.00),
            (
                "Teste preventivo de sensor de alarme (por sensor)",
                "un",
                True,
                12,
                22.00,
            ),
            ("Visita técnica e deslocamento (SISR)", "vb", True, 1, 280.00),
        ],
        photos=[
            Photo(
                "IMG_20261112_084215.jpg",
                "real_photos_itau/motion_sensor__old/ia_openai_1794211658_00.jpg",
                (0.18, 0.0, 0.9, 0.86),
                "sensor de presença antigo da tesouraria",
            ),
            Photo(
                "IMG_20261112_084430.jpg",
                "real_photos_itau/motion_sensor__old/ia_openai_1794297324_00.jpg",
                (0.08, 0.06, 0.84, 0.92),
                "sensor de presença, vista de perto",
            ),
        ],
        readme=(
            "Chamado 04175012 - Sensor de presença da tesouraria com disparo falso (aprovação do orçamento, SISR).\n\n"
            "Problemas plantados (o que o parecer deveria apontar):\n"
            "- QUANTIDADE ACIMA: o escopo e a solução falam de UM sensor (o da tesouraria); o orçamento cobra 3 sensores e\n"
            "  3 mãos de obra de substituição (itens 1 e 2).\n"
            "- PREÇO ACIMA DA REFERÊNCIA: sensor IVP a R$ 190 contra R$ 140 da LPU (ALA-002), 36% acima.\n"
            "Itens corretos: teste dos sensores (item 3) e a visita (item 4).\n"
            "Chamados da mesma agência: 04173506 (leitor biométrico da porta da tesouraria, aberto 8 dias antes e ainda\n"
            "aberto) entra na comparação pelos ainda abertos -> mesmo ambiente, OUTRO PROBLEMA (chance baixa).\n"
        ),
    ),
    Case(
        ticket_id="04175207",
        workstream="SETA",
        category="lighting",
        symptom="luminaria_danificada",
        scope=(
            "Hall dos caixas eletrônicos escuro, luminárias do teto apagadas perto da entrada. À noite os clientes "
            "reclamam que não enxergam o teclado do caixa."
        ),
        solution="Substituição das luminárias antigas do hall por luminárias LED 60x60.",
        branch={
            "code": "6260",
            "name": "Indaiatuba - Vila Sfeir",
            "environment": "area_interna_publico",
        },
        supplier="Luminar Serviços Elétricos LTDA",
        opening="2026-11-12",
        submission="2026-11-13",
        quote_file="Orcamento_Luminar_04175207.xlsx",
        items=[
            ("Luminária LED de embutir 60x60, 40 W", "un", True, 6, 385.00),
            ("Mão de obra de instalação de luminária", "un", True, 6, 80.00),
            (
                "Descarte de luminárias e lâmpadas (logística reversa)",
                "vb",
                True,
                1,
                360.00,
            ),
            ("Visita técnica e deslocamento", "vb", True, 1, 150.00),
        ],
        photos=[
            Photo(
                "IMG_20261112_183040.jpg",
                "real_photos_itau/ceiling_view/ia_openai_1794211347_00.jpg",
                (0.0, 0.0, 0.74, 0.7),
                "luminárias antigas do hall apagadas",
            ),
            Photo(
                "IMG_20261112_183215.jpg",
                "real_photos_itau/cctv_view__atm/ia_openai_1794211159_01.jpg",
                (0.24, 0.18, 1.0, 0.92),
                "hall dos caixas eletrônicos",
            ),
        ],
        readme=(
            "Chamado 04175207 - Hall dos caixas eletrônicos escuro (aprovação do orçamento).\n\n"
            "Problemas plantados (o que o parecer deveria apontar):\n"
            '- POSSÍVEL CHAMADO DUPLICADO: o chamado 04168903 (mesma agência 6260, "Lâmpada queimada do hall dos caixas\n'
            '  eletrônicos", aberto 2 dias antes, sem fotos e com a cotação de 2 lâmpadas T8) trata da mesma falta de luz\n'
            "  no hall, com outra categoria (Elétrica / Energia parcial) -> possible_duplicate_ticket -> ANÁLISE DETALHADA.\n"
            "- TROCA SEM JUSTIFICATIVA / QUANTIDADE ACIMA: o pedido é o hall escuro perto da entrada; o orçamento troca 6\n"
            "  luminárias inteiras, e as fotos mostram 2 luminárias antigas apagadas (o outro chamado orçou só 2 lâmpadas).\n"
        ),
    ),
    # ------------------------------------------------------------------ item Não LPU com similar na LPU
    Case(
        ticket_id="04175318",
        workstream="SETA",
        category="civil",
        symptom="rachadura_ou_trinca",
        scope=(
            "Parede de divisória do arquivo do backoffice rachada de cima a baixo e com placas soltas depois que um "
            "carrinho de caixas bateu nela; a parede balança quando alguém encosta. Trocar a divisória entre o arquivo e "
            "o corredor (cerca de 2,8 m de largura por 2,8 m de altura, 8 m²)."
        ),
        solution=(
            "Retirada da divisória danificada e montagem de parede nova de 8 m² entre o arquivo e o corredor, com "
            "pintura da face do corredor."
        ),
        branch={
            "code": "3057",
            "name": "Sorocaba Centro",
            "environment": "area_interna_backoffice",
        },
        supplier="Paredes & Cia Construções LTDA",
        opening="2026-11-16",
        submission="2026-11-17",
        quote_file="Orcamento_ParedesCia_04175318.xlsx",
        items=[
            (
                "Parede removível com montagem (painéis e estrutura)",
                "m²",
                False,
                8,
                210.00,
            ),
            ("Retirada e descarte da divisória danificada", "vb", False, 1, 180.00),
            (
                "Pintura interna em látex acrílico, paredes, 2 demãos",
                "m²",
                True,
                8,
                35.00,
            ),
            ("Visita técnica e deslocamento (SETA)", "vb", True, 1, 150.00),
        ],
        photos=[
            Photo(
                "IMG_20261116_101420.jpg",
                "real_photos_itau/storage/ia_openai_1794211923_00.jpg",
                (0.0, 0.04, 0.8, 0.9),
                "arquivo do backoffice, divisória com o corredor",
            ),
            Photo(
                "IMG_20261116_101655.jpg",
                "real_photos_itau/storage/ia_openai_1794297468_02.jpg",
                (0.12, 0.0, 0.9, 0.82),
                "arquivo do backoffice, vista da porta",
            ),
        ],
        readme=(
            "Chamado 04175318 - Divisória do arquivo do backoffice rachada (aprovação do orçamento, SETA).\n\n"
            "Problema plantado (o que o parecer deveria apontar):\n"
            '- ITEM NÃO LPU COM SIMILAR NA LPU: o item 1 "Parede removível com montagem" vem marcado como Não LPU, mas a\n'
            "  LPU da SETA tem a parede de drywall (DRY-001, R$ 145,00/m²), que cumpre a mesma função. Cobrado a\n"
            "  R$ 210,00/m² em 8 m²: R$ 520,00 acima do similar -> similar_lpu_item (valor potencial divergente R$ 520).\n"
            "- PREÇO SEM REFERÊNCIA: o item 2 (retirada e descarte da divisória, R$ 180) também é Não LPU e não tem\n"
            "  similar na LPU nem preço de mercado anexado -> price_not_comparable (contraste com o item 1).\n"
            "Itens corretos: pintura da face do corredor (8 m², LPU) e a visita.\n"
            "Resultado esperado: APROVAR COM RESSALVAS (cerca de 23% do orçamento em questão).\n"
        ),
    ),
    Case(
        ticket_id="04175420",
        workstream="SISR",
        category="alarm",
        symptom="sensor_com_defeito",
        scope=(
            "Sensor de presença do saguão não detecta ninguém: na central a zona 6 fica sempre em repouso, mesmo passando "
            "na frente do sensor. O alarme arma com a zona sem proteção."
        ),
        solution="Troca do sensor de presença do saguão e teste da zona 6 na central de alarme.",
        branch={"code": "5128", "name": "Curitiba Batel", "environment": "saguao"},
        supplier="Sentinela Segurança Eletrônica LTDA",
        opening="2026-11-17",
        submission="2026-11-18",
        quote_file="Orcamento_Sentinela_04175420.xlsx",
        items=[
            (
                "Sensor de presença infravermelho digital com fio, alcance 12 m",
                "un",
                False,
                1,
                245.00,
            ),
            ("Mão de obra de substituição de sensor", "un", True, 1, 110.00),
            ("Teste preventivo de sensor de alarme (por sensor)", "un", True, 1, 22.00),
            ("Deslocamento técnico até a agência", "vb", False, 1, 280.00),
        ],
        photos=[
            Photo(
                "IMG_20261117_150210.jpg",
                "real_photos_itau/motion_sensor/ia_openai_1794211612_00.jpg",
                (0.1, 0.0, 0.88, 0.84),
                "sensor de presença no canto do saguão",
            ),
            Photo(
                "IMG_20261117_150425.jpg",
                "real_photos_itau/motion_sensor/ia_openai_1794211612_01.jpg",
                (0.0, 0.08, 0.78, 0.92),
                "sensor de presença do saguão, outro ângulo",
            ),
        ],
        readme=(
            "Chamado 04175420 - Sensor de presença do saguão sem detecção (aprovação do orçamento, SISR).\n\n"
            "Problemas plantados (o que o parecer deveria apontar):\n"
            "- ITEM NÃO LPU COM SIMILAR NA LPU (com excedente): o item 1, sensor infravermelho digital com fio, vem como\n"
            "  Não LPU, mas a LPU da SISR tem o sensor infravermelho passivo (IVP) com fio (ALA-002, R$ 140,00). Cobrado a\n"
            "  R$ 245,00: R$ 105,00 acima do similar -> similar_lpu_item.\n"
            "- ITEM NÃO LPU COM SIMILAR NA LPU (sem excedente): o item 4, deslocamento técnico, vem como Não LPU, mas\n"
            "  equivale à visita técnica e deslocamento da SISR (SIS-001, R$ 280,00), pelo mesmo preço -> similar_lpu_item\n"
            "  sem valor em questão (o fornecedor deveria ter usado o item da LPU).\n"
            "Itens corretos: mão de obra de substituição e teste do sensor (LPU).\n"
            "Resultado esperado: APROVAR COM RESSALVAS (cerca de 16% do orçamento em questão).\n"
        ),
    ),
]


# ------------------------------------------------------------------ chamado com muitas fotos (100+)
# Vistoria geral da agência, com fotos de todos os ambientes, como os chamados do Itaú que chegam com 100+ fotos e
# estouravam o limite de tokens de saída numa chamada só. Cada imagem da biblioteca rende três recortes (três fotos do
# mesmo ponto, com enquadramentos diferentes); as imagens já usadas por outro caso desta lista ficam de fora, para não
# parecerem reaproveitamento. As fotos de câmera de segurança no meio da sequência estão ali de propósito (fora do escopo).
BULK_SOURCES: list[tuple[str, str]] = (
    [  # pasta da biblioteca, o que a foto mostra (vai no EXIF)
        ("ceiling_view__stains", "forro do salão com manchas de umidade"),
        ("backoffice__stains", "forro do backoffice manchado"),
        ("storage", "arquivo do backoffice"),
        ("backoffice__lights_off", "luminárias apagadas no backoffice"),
        ("ceiling_view", "luminárias do salão de atendimento"),
        ("ceiling_view__led", "teto do salão com as luminárias"),
        ("outlets__burned", "tomada queimada em estação de trabalho"),
        ("outlets", "tomadas das estações de trabalho"),
        ("door_closer", "mola aérea de porta batendo"),
        ("door_closer__detail", "mola aérea vazando óleo, detalhe"),
        ("under_sink_leak", "vazamento no sifão da pia do banheiro"),
        ("bathroom", "banheiro dos funcionários"),
        ("ac_filter__dirty", "filtro de split sujo"),
        ("ac_filter", "filtro de split"),
    ]
)
BULK_OFF_SCOPE: list[tuple[str, str]] = (
    [  # plantadas: nada a ver com o escopo (SISR, não SETA)
        ("cctv_view__corridor", "imagem de câmera de segurança do corredor"),
        ("cctv_view__parking", "imagem de câmera de segurança do estacionamento"),
    ]
)
# três cantos: o recorte central parecia demais com as fotos do conjunto itau (02…), que usam a imagem quase inteira
BULK_CROPS = (
    (0.0, 0.0, 0.66, 0.7),
    (0.34, 0.0, 1.0, 0.7),
    (0.34, 0.3, 1.0, 1.0),
)
BULK_OFF_SCOPE_CROP = (0.1, 0.08, 0.86, 0.9)


def bulk_photos(day: str, start: str, used: set[str]) -> list[Photo]:
    """Fotos da vistoria, na ordem em que o técnico percorre a agência (nomes com hora crescente).

    Args:
        day: data das fotos (AAAAMMDD).
        start: hora da primeira foto (HHMMSS).
        used: origens já usadas por outros casos (ficam de fora).

    Returns:
        Três recortes por imagem da biblioteca (sem as já usadas) e, no meio da sequência, um recorte de cada imagem de
        câmera de segurança. Sem a biblioteca (fora do git), a lista sai vazia e `build` avisa.
    """
    rnd = random.Random(f"bulk-{day}")
    clock = datetime.strptime(f"{day}{start}", "%Y%m%d%H%M%S")

    def sources(folders: list[tuple[str, str]]) -> list[tuple[str, str]]:
        out = []
        for folder, desc in folders:
            for f in sorted((LIBRARY / folder).glob("*.jpg")):
                src = f"real_photos_itau/{folder}/{f.name}"
                if src not in used:
                    out.append((src, desc))
        return out

    plan: list[tuple[str, str, tuple[float, float, float, float]]] = [
        (src, desc, crop) for src, desc in sources(BULK_SOURCES) for crop in BULK_CROPS
    ]
    # as fotos fora do escopo entram no meio (caem num lote do meio quando a análise é dividida)
    middle = len(plan) // 2
    plan[middle:middle] = [
        (src, desc, BULK_OFF_SCOPE_CROP) for src, desc in sources(BULK_OFF_SCOPE)
    ]
    photos = []
    for src, desc, crop in plan:
        clock += timedelta(seconds=rnd.randint(35, 110))
        photos.append(Photo(f"IMG_{clock:%Y%m%d_%H%M%S}.jpg", src, crop, desc))
    return photos


def bulk_case() -> Case:
    used = {p.source for c in CASES for p in c.photos}
    photos = bulk_photos("20261118", "084000", used)
    return Case(
        ticket_id="04175533",
        workstream="SETA",
        category="civil",
        symptom="pecas_e_equipamentos_diversos",
        scope=(
            "Vistoria geral da agência feita pelo gerente com o fornecedor. Problemas encontrados: forro manchado e com "
            "infiltração no salão de atendimento e no backoffice (cerca de 14 m²); 6 luminárias apagadas entre o salão e "
            "o backoffice; 6 tomadas queimadas ou esquentando nas estações de trabalho; molas aéreas das portas do "
            "backoffice e do banheiro vazando óleo e batendo a porta; vazamento no sifão da pia do banheiro dos "
            "funcionários; 4 aparelhos split com filtro sujo, sem limpeza há meses. Fotos de todos os pontos em anexo."
        ),
        solution=(
            "Correção dos itens da vistoria: tratamento da infiltração e recomposição do forro com pintura, troca das 6 "
            "luminárias por LED, troca das 6 tomadas, troca das 2 molas aéreas, troca do sifão e limpeza com "
            "higienização dos 4 splits."
        ),
        branch={
            "code": "3390",
            "name": "Ribeirão Preto Centro",
            "environment": "area_interna_toda_agencia",
        },
        supplier="Manutec Facilities e Engenharia LTDA",
        opening="2026-11-18",
        submission="2026-11-20",
        quote_file="Orcamento_Manutec_04175533.xlsx",
        items=[
            ("Recomposição de forro de gesso (recorte e reposição)", "m²", True, 14, 95.00),
            ("Tratamento de infiltração com manta líquida/impermeabilizante", "m²", True, 16, 68.00),
            ("Aplicação de fundo preparador antimofo", "m²", True, 14, 6.50),
            ("Pintura de teto/forro em látex, 2 demãos", "m²", True, 14, 35.00),
            ("Luminária LED de embutir 60x60, 40 W", "un", True, 6, 385.00),
            ("Mão de obra de instalação de luminária", "un", True, 6, 80.00),
            ("Descarte de luminárias e lâmpadas (logística reversa)", "vb", True, 1, 360.00),
            ("Tomada 2P+T 10 A com placa", "un", True, 6, 28.00),
            ("Mão de obra de substituição de tomada", "un", True, 6, 35.00),
            ("Mola aérea (fecha-porta) para porta até 80 kg", "un", True, 2, 420.00),
            ("Mão de obra de instalação de mola aérea", "un", True, 2, 150.00),
            ("Sifão de PVC para pia", "un", True, 1, 38.00),
            ("Mão de obra hidráulica", "h", True, 2, 85.00),
            ("Limpeza preventiva de split até 24.000 BTU (evaporadora + condensadora)", "un", True, 4, 180.00),
            ("Higienização com bactericida (por aparelho)", "un", True, 4, 45.00),
            ("Pintura de fachada com tinta acrílica externa", "m²", True, 85, 38.00),
            ("Visita técnica e deslocamento (SETA)", "vb", True, 1, 150.00),
        ],  # fmt: skip
        photos=photos,
        readme=(
            f"Chamado 04175533 - Vistoria geral da agência com {len(photos)} fotos (aprovação do orçamento).\n\n"
            "Para que serve: testar chamado com MUITAS fotos, como os do Itaú com 100+ que davam erro de max_tokens.\n"
            "Com [llm] max_images_per_call = 20, a identificação dos anexos e a análise das fotos vão em lotes de 20; no\n"
            "log aparecem attachments_chunked e photos_chunked (proactive=True), sem 'resposta cortada'.\n"
            "O que conferir: o parecer sai (sem erro), com TODAS as fotos na aba Fotos e nenhum anexo 'não identificado'.\n\n"
            "Problemas plantados (o que o parecer deveria apontar):\n"
            "- ITEM FORA DO ESCOPO: o item 16, pintura de fachada (85 m² x R$ 38,00 = R$ 3.230,00, cerca de 27% do\n"
            "  orçamento), não aparece na vistoria nem na solução, e nenhuma foto mostra a fachada -> out_of_scope_item.\n"
            "- FOTOS FORA DO ESCOPO: no meio da sequência há imagens de câmera de segurança (corredor e estacionamento),\n"
            "  que não têm relação com a vistoria de infraestrutura -> photo_mismatch (uma por foto). Elas caem num lote\n"
            "  do meio: servem para conferir que o apontamento de um lote sobrevive à junção dos lotes.\n"
            "Os demais itens são da LPU, pelo preço da LPU, e batem com a vistoria. Com tantas fotos, a contagem por item\n"
            "(quantidade cobrada x fotos) pode variar no modelo real: confira o raciocínio na aba Fotos.\n"
        ),
    )


CASES.append(bulk_case())


# ------------------------------------------------------------------ SISR: relatório em PDF no formato checklist
# Boa parte dos fornecedores da SISR manda só um PDF: cada pergunta, a resposta Sim/Não marcada e a foto que a demonstra,
# sem fotos soltas. As fotos são extraídas do PDF (atest/pdf_photos.py) e analisadas como as outras.
def report_photo(
    name: str, source: str, crop: tuple[float, float, float, float], desc: str
) -> Photo:
    return Photo(name, f"real_photos_itau/{source}", crop, desc)


CASES.append(
    Case(
        ticket_id="04175640",
        workstream="SISR",
        category="cctv",
        symptom="no_image",
        scope=(
            "Câmera 05, externa, sobre a entrada do autoatendimento, vandalizada: está sem imagem no gravador desde o fim "
            "de semana. A entrada do autoatendimento fica sem monitoramento."
        ),
        solution=(
            "Substituição da câmera 05 por câmera IP bullet nova, com eletroduto e caixa antivandalismo, e teste da imagem "
            "e da gravação no gravador."
        ),
        branch={
            "code": "5590",
            "name": "Niterói Icaraí",
            "environment": "area_externa",
        },
        supplier="Vigilância Total Sistemas de Segurança LTDA",
        opening="2026-11-16",
        submission="2026-11-19",
        moment="execution",
        quote_file="Orcamento_VigilanciaTotal_04175640.xlsx",
        items=[
            ("Câmera IP bullet 4 MP", "un", True, 1, 2300.00),
            ('Eletroduto galvanizado 3/4" com caixa de passagem antivandalismo', "m", True, 4, 38.00),
            ("Conector/balun e reconexão", "un", True, 2, 40.00),
            ("Mão de obra técnica de segurança (hora)", "h", True, 3, 110.00),
            ("Visita técnica e deslocamento (SISR)", "vb", True, 1, 280.00),
        ],  # fmt: skip
        photos=[],
        report=Report(
            file="Relatorio_Atendimento_04175640.pdf",
            title="Relatório de Atendimento Técnico - CFTV",
            header=[
                "Fornecedor: Vigilância Total Sistemas de Segurança LTDA",
                "Chamado: 04175640    Agência: 5590 - Niterói Icaraí",
                "Data do atendimento: 18/11/2026    Início: 09:10    Término: 11:40",
                "Técnico: Carlos A. Souza    Equipamento: Câmera 05 (externa, entrada do autoatendimento)",
            ],
            items=[
                ReportItem(
                    "O equipamento estava vandalizado?",
                    True,
                    note="Lente quebrada e cabo arrancado",
                ),
                ReportItem(
                    "A câmera foi substituída por uma nova?",
                    True,
                    report_photo(
                        "IMG_20261118_101530.jpg",
                        "bullet_camera_wall/ia_openai_1794211111_01.jpg",
                        (0.0, 0.0, 0.7, 0.74),
                        "câmera bullet nova instalada",
                    ),
                ),
                ReportItem(
                    "A câmera foi fixada com eletroduto e caixa antivandalismo?",
                    True,
                    report_photo(
                        "IMG_20261118_102210.jpg",
                        "bullet_camera_wall/ia_openai_1794211111_00.jpg",
                        (0.3, 0.2, 1.0, 1.0),
                        "câmera com eletroduto na parede",
                    ),
                ),
                ReportItem(
                    "A imagem da câmera 05 aparece no gravador, mostrando a entrada do autoatendimento?",
                    True,
                    report_photo(
                        "IMG_20261118_111045.jpg",
                        "cctv_view__office/ia_openai_1794211289_00.jpg",
                        (0.0, 0.0, 0.72, 0.76),
                        "tela do gravador",
                    ),
                ),
                ReportItem(
                    "A gravação foi testada (reprodução das últimas horas)?",
                    True,
                    note="Reprodução ok; HD com 30 dias de gravação",
                ),
                ReportItem("A câmera antiga foi recolhida pela empresa?", True),
                ReportItem(
                    "O gerente da agência acompanhou o teste?",
                    True,
                    note="Gerente João Martins",
                ),
            ],
            footer=[
                "Declaro que o serviço foi executado conforme descrito acima.",
                "Responsável na agência: João Martins (gerente) - assinado",
            ],
        ),
        readme=(
            "Chamado 04175640 - Câmera externa vandalizada, sem imagem (retorno após a execução, SISR).\n\n"
            "Para que serve: testar o formato de relatório mais comum na SISR. O fornecedor mandou só o orçamento e um PDF\n"
            "no formato checklist (pergunta, resposta Sim/Não marcada e a foto que a demonstra), SEM fotos soltas.\n"
            "O Atest.AI extrai as 3 fotos de dentro do PDF (attachments/Relatorio_..._p01_foto01.jpg etc., com o manifesto\n"
            ".fotos.json) e as analisa como fotos, com a pergunta e a resposta ao lado. Antes disso, o chamado era devolvido\n"
            "no checklist mínimo (nenhum anexo de foto) e as fotos do PDF não eram conferidas.\n\n"
            "O que conferir: o checklist passa (foto do equipamento e imagem da câmera vêm do PDF); na aba Fotos, as 3 fotos\n"
            "com 'Página N do Relatorio_...pdf' e o texto da pergunta; na aba Documentos, as 7 perguntas com as respostas.\n\n"
            "Problema plantado (o que o parecer deveria apontar):\n"
            "- RESPOSTA CONTRADITA PELA FOTO: a pergunta 4 diz que a imagem da câmera 05 aparece no gravador mostrando a\n"
            "  ENTRADA DO AUTOATENDIMENTO (Sim), mas a foto ao lado mostra a imagem de uma câmera INTERNA, do backoffice\n"
            "  (mesas, computadores, armários) -> report_answer_contradicted. Sem imagem da câmera 05 funcionando, a prova\n"
            "  do serviço também fica em dúvida (sem foto do concluído ou local não confirmado).\n"
            "- A pergunta 1 (vandalizado: Sim) não tem foto: pode sair 'sem foto do antes'.\n"
            "- CAUSA ESPECIAL COM SINTOMA ERRADO: a câmera foi vandalizada (escopo e pergunta 1: Sim), mas o chamado foi\n"
            "  aberto como Cftv / Sem imagem -> cause_miscategorized (o sintoma certo seria Vandalismo), que leva à\n"
            "  análise detalhada.\n"
            "Orçamento: itens e preços da LPU da SISR, coerentes com a troca de uma câmera.\n"
        ),
    )
)


# ------------------------------------------------------------------ categoria e solução
CASES += [
    Case(
        ticket_id="04175751",
        workstream="SETA",
        category="electrical",
        symptom="vandalismo",
        scope=(
            "Tomada da bancada do caixa 2 danificada por vandalismo: um cliente forçou um carregador na tomada e ela "
            "ficou inutilizada. A tomada está sem uso e com risco de choque."
        ),
        solution="Substituição da tomada da bancada do caixa 2.",
        branch={
            "code": "3871",
            "name": "Curitiba Batel",
            "environment": "area_interna_publico",
        },
        supplier="Paraná Instalações Prediais LTDA",
        opening="2026-11-18",
        submission="2026-11-19",
        quote_file="Orcamento_ParanaInstalacoes_04175751.xlsx",
        items=[
            ("Tomada 2P+T 10 A com placa", "un", True, 1, 28.00),
            ("Mão de obra de substituição de tomada", "un", True, 1, 35.00),
            ("Visita técnica e deslocamento (SETA)", "vb", True, 1, 150.00),
        ],
        photos=[
            Photo(
                "IMG_20261118_101205.jpg",
                "real_photos_itau/outlets__burned/ia_openai_1794297398_01.jpg",
                (0.12, 0.08, 0.92, 0.9),
                "tomada da bancada do caixa 2, enegrecida e derretida",
            ),
            Photo(
                "IMG_20261118_101322.jpg",
                "real_photos_itau/outlets__burned/ia_openai_1794297398_00.jpg",
                (0.05, 0.1, 0.8, 0.95),
                "tomada da bancada, outro ângulo",
            ),
        ],
        readme=(
            "Chamado 04175751 - Tomada do caixa 2 aberta como VANDALISMO (aprovação do orçamento, SETA).\n\n"
            "Para que serve: testar a conferência de categoria e sintoma com as evidências (etapa 'Categoria e\n"
            "solução'). Vandalismo e desastre natural têm tratamento próprio (B.O., seguro, verba), então abrir um defeito\n"
            "comum como vandalismo é um problema.\n\n"
            "Problema plantado (o que o parecer deveria apontar):\n"
            "- CAUSA ERRADA: o chamado foi aberto como Elétrica / Vandalismo ('cliente forçou um carregador'), mas as fotos\n"
            "  mostram a tomada ENEGRECIDA e DERRETIDA em volta dos furos: marca de aquecimento (mau contato ou sobrecarga),\n"
            "  não de quebra por força -> cause_miscategorized ('Vandalismo/desastre com categoria errada'), que leva à\n"
            "  análise detalhada. O sintoma certo seria 'Tomada ou interruptor danificado'.\n"
            "A solução (trocar a tomada) e o orçamento (itens da LPU) são coerentes com o problema.\n"
        ),
    ),
    Case(
        ticket_id="04175862",
        workstream="SETA",
        category="civil",
        symptom="moisture_infiltration",
        scope=(
            "Forro do salão de atendimento, acima do totem de senhas, com manchas de infiltração e mofo em várias placas. "
            "As manchas crescem e pinga água nos dias de chuva forte."
        ),
        solution="Troca das placas de forro manchadas, aplicação de antimofo e pintura do forro.",
        branch={
            "code": "6104",
            "name": "Recife Boa Viagem",
            "environment": "area_interna_publico",
        },
        supplier="Nordeste Reformas e Manutenção LTDA",
        opening="2026-11-20",
        submission="2026-11-21",
        quote_file="Orcamento_NordesteReformas_04175862.xlsx",
        items=[
            (
                "Recomposição de forro (troca das placas manchadas)",
                "m²",
                True,
                8,
                95.00,
            ),
            ("Aplicação de fundo preparador antimofo", "m²", True, 8, 6.50),
            ("Pintura de teto/forro em látex, 2 demãos", "m²", True, 8, 35.00),
            ("Visita técnica e deslocamento (SETA)", "vb", True, 1, 150.00),
        ],
        photos=[
            Photo(
                "IMG_20261120_143010.jpg",
                "real_photos_itau/ceiling_view__stains/ia_openai_1794297247_02.jpg",
                (0.0, 0.0, 0.82, 0.78),
                "forro do salão com manchas de infiltração e mofo",
            ),
            Photo(
                "IMG_20261120_143127.jpg",
                "real_photos_itau/ceiling_view__stains/ia_openai_1794297247_01.jpg",
                (0.15, 0.05, 1.0, 0.85),
                "placas do forro manchadas, de perto",
            ),
        ],
        readme=(
            "Chamado 04175862 - Infiltração no forro do salão: a solução só troca e pinta o forro (aprovação do\n"
            "orçamento, SETA).\n\n"
            "Para que serve: testar a coerência da solução com o problema relatado (etapa 'Categoria e solução').\n\n"
            "Problema plantado (o que o parecer deveria apontar):\n"
            "- SOLUÇÃO NÃO TRATA A CAUSA: o problema é infiltração ('pinga água nos dias de chuva forte'), mas a solução e o\n"
            "  orçamento só trocam as placas, aplicam antimofo e pintam. Nada localiza nem corrige a origem da água (laje,\n"
            "  calha, telhado ou tubulação; a LPU tem IMP-001, tratamento de infiltração): na próxima chuva o forro novo\n"
            "  mancha de novo -> solution_partially_coherent ('Solução resolve só parte do problema') ou\n"
            "  solution_incoherent.\n"
            "Categoria e sintoma (Civil / Infiltração ou umidade) estão certos; itens e preços batem com a LPU.\n"
        ),
    ),
]


# ============================================================================ geração
def exif_bytes(photo: Photo, ticket_id: str) -> bytes:
    stamp = photo.taken_at.strftime("%Y:%m:%d %H:%M:%S").encode()
    note = (
        f"Imagem simulada para teste do Atest.AI - caso ficticio {ticket_id}. {photo.description}. "
        "Nao e evidencia real."
    )
    note = note.encode("ascii", "ignore")
    zeroth = {
        piexif.ImageIFD.ImageDescription: note,
        piexif.ImageIFD.Software: b"Atest.AI - imagem simulada",
        piexif.ImageIFD.DateTime: stamp,
    }
    exif = {
        piexif.ExifIFD.DateTimeOriginal: stamp,
        piexif.ExifIFD.DateTimeDigitized: stamp,
    }
    return piexif.dump(
        {"0th": zeroth, "Exif": exif, "GPS": {}, "1st": {}, "thumbnail": None}
    )


def make_photo(photo: Photo, ticket_id: str, target: Path) -> None:
    """Recorta, ajusta (brilho e contraste leves, só nas fotos da biblioteca) e grava com o EXIF do caso."""
    src = ROOT / "data" / photo.source
    if not src.exists():
        raise SystemExit(
            f"Foto de origem não encontrada: {src}. A biblioteca data/real_photos_itau fica fora do git "
            "(veja generator/ai_photos.py)."
        )
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        x0, y0, x1, y1 = photo.crop
        im = im.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))
        if not photo.reused_from:
            # outro "celular": enquadramento já mudou; brilho e contraste levemente diferentes
            rnd = random.Random(photo.name)
            im = ImageEnhance.Brightness(im).enhance(rnd.uniform(0.92, 1.06))
            im = ImageEnhance.Contrast(im).enhance(rnd.uniform(0.94, 1.08))
            scale = MAX_SIDE / max(im.size)
            im = im.resize(
                (round(im.width * scale), round(im.height * scale)), Image.LANCZOS
            )
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=photo.quality, exif=exif_bytes(photo, ticket_id))
    target.write_bytes(buf.getvalue())


def make_quote(case: Case, target: Path) -> None:
    """Planilha só com a aba Itens (formato tbItens do modelo do painel)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Itens"
    ws.append(ITEM_HEADER)
    for desc, unit, lpu, qty, value in case.items:
        ws.append([desc, unit, "Sim" if lpu else "Não", qty, value])
    tab = Table(displayName="tbItens", ref=f"A1:E{len(case.items) + 1}")
    tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(tab)
    for col, width in zip("ABCDE", WIDTHS, strict=True):
        ws.column_dimensions[col].width = width
    wb.save(target)


def make_report(case: Case, target: Path) -> None:
    """Relatório em PDF no formato checklist: cada foto é gerada como as soltas (recorte + EXIF) e embutida no PDF."""
    assert case.report is not None
    questions = []
    for q in case.report.items:
        data = None
        if q.photo:
            tmp = target.with_name(f"_tmp_{q.photo.name}")
            make_photo(q.photo, case.ticket_id, tmp)
            data = tmp.read_bytes()
            tmp.unlink()
        questions.append(Question(q.text, q.answer, data, q.note))
    target.write_bytes(
        render_report(
            case.report.title, case.report.header, questions, case.report.footer
        )
    )


def build(case: Case, force: bool) -> bool:
    if not case.photos and not case.report:
        raise SystemExit(
            f"{case.ticket_id}: nenhuma foto de origem. A biblioteca {LIBRARY} fica fora do git "
            "(veja generator/ai_photos.py)."
        )
    folder = TICKETS / case.ticket_id
    if folder.exists():
        if not force:
            print(f"{case.ticket_id}: já existe (use --force para regerar)")
            return False
        shutil.rmtree(folder)
    att = folder / "attachments"
    att.mkdir(parents=True)
    make_quote(case, att / case.quote_file)
    for p in case.photos:
        make_photo(p, case.ticket_id, att / p.name)
    if case.report:
        make_report(case, att / case.report.file)
    upload = case.submission
    attachments = [
        {"file_name": case.quote_file, "content_type": XLSX, "size_bytes": (att / case.quote_file).stat().st_size,
         "sent_by": "supplier", "data_upload": upload}
    ] + [
        {"file_name": p.name, "content_type": "image/jpeg", "size_bytes": (att / p.name).stat().st_size,
         "sent_by": "supplier", "data_upload": upload}
        for p in case.photos
    ] + ([
        {"file_name": case.report.file, "content_type": "application/pdf",
         "size_bytes": (att / case.report.file).stat().st_size, "sent_by": "supplier", "data_upload": upload}
    ] if case.report else [])  # fmt: skip
    total = round(sum(q * v for _, _, _, q, v in case.items), 2)
    ticket = {
        "ticket_id": case.ticket_id,
        "workstream": case.workstream,
        "maintenance_type": case.maintenance_type,
        "moment": case.moment,
        "category": case.category,
        "symptom": case.symptom,
        "requested_scope": case.scope,
        "solution_description": case.solution,
        "branch": case.branch,
        "supplier": {"name": case.supplier, "cnpj": ""},
        "blocks_opening": case.blocks_opening,
        "quoted_value": total,
        "dates": {
            "opening": case.opening,
            "supplier_submission": case.submission,
            "manager_review": None,
        },
        "status": case.status,
        "origin": "dataset",
        "dataset": "casos",
        "manager": {"first_check": "forwarded", "note": ""},
        "attachments": attachments,
        **case.extra,
    }
    (folder / "ticket.json").write_text(
        json.dumps(ticket, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    all_photos = case.photos + (case.report.photos if case.report else [])
    origin = (
        LIB_ORIGIN
        if any(not p.reused_from for p in all_photos)
        else "cópias de fotos de outro chamado"
    )
    if any(p.reused_from for p in all_photos) and any(
        not p.reused_from for p in all_photos
    ):
        origin += "; e cópias de fotos de outro chamado, de propósito"
    if case.report:
        origin += f"; as do relatório estão DENTRO do PDF {case.report.file}"
    (folder / "LEIAME.txt").write_text(
        HEADER.format(origin=origin) + case.readme, encoding="utf-8"
    )
    where = f" dentro do PDF {case.report.file}" if case.report else ""
    print(
        f"{case.ticket_id}: gerado ({len(all_photos)} fotos{where}, orçamento R$ {total:,.2f})"
    )
    return True


# ============================================================================ conferência
def check() -> bool:
    """Toda foto dos casos desta lista comparada com TODAS as fotos de outros chamados (atuais e histórico), sem olhar
    data: só as reaproveitadas de propósito podem ficar dentro do limite da régua, e da origem esperada.
    """
    cfg = load_settings()
    rubric = cfg.rubric
    index = PhotoIndex.from_folders(
        cfg.history_dir, cfg.tickets_dir, crops=rubric.hash_crops
    )
    ok = True
    for case in CASES:
        folder = TICKETS / case.ticket_id
        # fotos soltas pelo nome; as do relatório em PDF, pelos anexos extraídos do PDF (como o pipeline as vê)
        checks = [
            (p.name, folder / "attachments" / p.name, p.reused_from)
            for p in case.photos
        ]
        if case.report and (folder / "ticket.json").exists():
            checks += [
                (a.name, a.path, "")
                for a in load_ticket(folder).attachments
                if a.source
            ]
        for name, path, reused_from in checks:
            if not path.exists():
                continue
            h, det = compute_hashes(path), detail_level(path)
            best: tuple[int, str] | None = None
            for r in index.records:
                if r.ticket_id == case.ticket_id:
                    continue
                d = min(distance(h, x) for x in r.hashes)
                low = min(det, r.detail_level) < rubric.hash_min_detail
                limit = (
                    rubric.hash_max_distance_low_detail
                    if low
                    else rubric.hash_max_distance
                )
                if d <= limit and (best is None or d < best[0]):
                    best = (d, f"{r.ticket_id}/{r.file}")
            if reused_from:
                good = best is not None and best[1] == reused_from
                print(f"  {case.ticket_id}/{name}: reaproveitada de {reused_from} -> "
                      f"{'detectada' if good else 'NÃO DETECTADA'} {best or ''}")  # fmt: skip
            else:
                good = best is None
                if not good:
                    print(
                        f"  {case.ticket_id}/{name}: parece com {best[1]} (distância {best[0]}): troque o recorte"
                    )
            ok &= good
    print("Conferência das fotos:", "ok" if ok else "FALHOU")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="regera os casos desta lista que já existem",
    )
    ap.add_argument(
        "--check", action="store_true", help="só confere a semelhança das fotos"
    )
    args = ap.parse_args()
    if not args.check:
        for case in CASES:
            build(case, args.force)
    if not check():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
