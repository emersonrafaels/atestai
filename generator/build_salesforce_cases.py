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
from datetime import datetime
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


def build(case: Case, force: bool) -> bool:
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
    upload = case.submission
    attachments = [
        {"file_name": case.quote_file, "content_type": XLSX, "size_bytes": (att / case.quote_file).stat().st_size,
         "sent_by": "supplier", "data_upload": upload}
    ] + [
        {"file_name": p.name, "content_type": "image/jpeg", "size_bytes": (att / p.name).stat().st_size,
         "sent_by": "supplier", "data_upload": upload}
        for p in case.photos
    ]  # fmt: skip
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
    origin = (
        LIB_ORIGIN
        if any(not p.reused_from for p in case.photos)
        else "cópias de fotos de outro chamado"
    )
    if any(p.reused_from for p in case.photos) and any(
        not p.reused_from for p in case.photos
    ):
        origin += "; e cópias de fotos de outro chamado, de propósito"
    (folder / "LEIAME.txt").write_text(
        HEADER.format(origin=origin) + case.readme, encoding="utf-8"
    )
    print(
        f"{case.ticket_id}: gerado ({len(case.photos)} fotos, orçamento R$ {total:,.2f})"
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
        for p in case.photos:
            path = TICKETS / case.ticket_id / "attachments" / p.name
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
            if p.reused_from:
                good = best is not None and best[1] == p.reused_from
                print(f"  {case.ticket_id}/{p.name}: reaproveitada de {p.reused_from} -> "
                      f"{'detectada' if good else 'NÃO DETECTADA'} {best or ''}")  # fmt: skip
            else:
                good = best is None
                if not good:
                    print(
                        f"  {case.ticket_id}/{p.name}: parece com {best[1]} (distância {best[0]}): troque o recorte"
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
