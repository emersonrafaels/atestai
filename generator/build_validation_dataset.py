"""Gera o CONJUNTO DE VALIDAÇÃO: chamados sintéticos com defeitos injetados de forma controlada.

    python generator/build_validation_dataset.py            # 80 chamados (8 por modelo de serviço)
    python generator/build_validation_dataset.py --n 12     # n por modelo

Cada chamado parte de um modelo coerente (escopo, itens da LPU e fotos de antes/depois) e recebe de 0 a 3 defeitos
sorteados (item fora do escopo, preço acima, foto de outro ambiente, foto reaproveitada, checklist incompleto...).
O gabarito é calculado aplicando a régua de config/rubric.toml aos defeitos injetados: assim o conjunto mede se o
modelo DETECTA os problemas, e a régua faz o resto.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(PROJECT_ROOT))

import real_photos  # noqa: E402
import scenes  # noqa: E402
from build_demo_dataset import attachment_meta, render_scene, save_jpg  # noqa: E402
from camera import photograph  # noqa: E402
from cases import LPU, SUPPLIER  # noqa: E402
from quotes import make_xlsx  # noqa: E402
from render import finish, illegible  # noqa: E402

from atest.attachments import distance, hashes_with_crops  # noqa: E402
from atest.config import load_settings  # noqa: E402
from atest.score import ScoreCalculator  # noqa: E402

CFG = load_settings()
ROOT = CFG.data_dir
BRANCHES = [
    ("0102", "Ag. Barra Funda"),
    ("0215", "Ag. Butantã"),
    ("0333", "Ag. Ipiranga"),
    ("0447", "Ag. Mooca"),
    ("0558", "Ag. Penha"),
    ("0661", "Ag. Saúde"),
    ("0774", "Ag. Vila Mariana"),
    ("0886", "Ag. Perdizes"),
    ("0991", "Ag. Campo Belo"),
    ("1010", "Ag. Morumbi"),
    ("1121", "Ag. Lapa de Baixo"),
    ("1232", "Ag. Santana"),
    ("1343", "Ag. Tucuruvi"),
    ("1454", "Ag. Jabaquara"),
]
OTHER_ROOMS = [
    ("bathroom", "Banheiro azulejado: outro ambiente"),
    ("storage", "Depósito com prateleiras: outro ambiente"),
    ("facade", "Fachada externa da agência"),
]
LPU_IDX = {e: {r[0]: r for r in rows} for e, rows in LPU.items()}

# ============================================================================ modelos de serviço
F = lambda scene, kw, cat, mom, desc: {"scene": scene, "kw": kw, "category": cat, "moment": mom, "description": desc}  # noqa: E731


@dataclass
class ServiceTemplate:
    name: str
    workstream: str
    category: str
    symptom: str
    maintenance: str
    supplier: str
    scope: str  # com {env} e {q}
    environments: list[str]
    q: tuple[int, int]
    items: list[tuple]  # (descrição, unidade, qtd: "q" | número, lpu)
    before: list[dict]
    after: list[dict]
    docs: list[str] = field(default_factory=list)  # termo | relatorio
    out: tuple | None = None
    replacement: tuple | None = None
    moment: str = "execution"
    before_applicable: bool = True
    material: int = 0  # índice do item cuja quantidade pode ser inflada
    vague: str = "Verificar {env}. Urgente."


def _cctv(rnd):
    return {"scene": rnd.choice(["atm", "corridor", "parking"]), "label": f"CAM {rnd.randint(1, 12):02d}"}


MODELS: list[ServiceTemplate] = [
    ServiceTemplate(
        "painting",
        "SETA",
        "painting",
        "finish_wear",
        "corrective",
        "Alfa",
        "Repintura das paredes do {env} (aprox. {q} m²), cor padrão da agência.",
        ["backoffice", "salão de atendimento"],
        (40, 160),
        [("Pintura látex acrílico em paredes, 2 demãos", "m²", "q", "PIN-001"), ("Massa corrida para correção de paredes", "m²", "q", "PIN-004")],
        before=[F("backoffice", {"stains": True, "view": "C"}, "room_before_photo", "before", "Paredes manchadas e descascando")],
        after=[F("backoffice", {"view": "A"}, "room_after_photo", "after", "Ambiente com paredes pintadas")],
        out=("Pintura de fachada com tinta acrílica externa", "m²", 60, "PIN-003"),
        material=1,
    ),
    ServiceTemplate(
        "infiltration",
        "SETA",
        "waterproofing",
        "moisture_infiltration",
        "corrective",
        "Delta",
        "Infiltração no forro do {env}: tratar a origem e recompor o forro de gesso (aprox. {q} m²).",
        ["backoffice", "kitchen"],
        (2, 8),
        [
            ("Impermeabilização com manta líquida", "m²", "q", "IMP-001"),
            ("Recomposição de forro de gesso", "m²", "q", "IMP-002"),
            ("Pintura de forro em látex", "m²", "q", "PIN-002"),
        ],
        before=[F("ceiling_view", {"stains": True}, "room_before_photo", "before", "Forro com mancha de infiltração e mofo")],
        after=[F("ceiling_view", {}, "room_after_photo", "after", "Forro recomposto e pintado")],
        out=("Pintura de paredes do salão", "m²", 40, "PIN-001"),
        material=1,
    ),
    ServiceTemplate(
        "lamps",
        "SETA",
        "lighting",
        "poor_lighting",
        "corrective",
        "Gama",
        "Trocar as {q} lâmpadas tubulares queimadas do {env}.",
        ["corridor", "backoffice"],
        (4, 12),
        [("Lâmpada LED tubular T8 18W", "un", "q", "ELE-008"), ("Mão de obra troca de lâmpada", "un", "q", "ELE-009")],
        before=[
            F(
                "backoffice",
                {"lights": "fluor", "dead": (0, 1, 3), "clutter": False, "view": "B"},
                "room_before_photo",
                "before",
                "Ambiente com lâmpadas apagadas",
            )
        ],
        after=[
            F("ceiling_view", {"lights": "led"}, "room_after_photo", "after", "Teto com lâmpadas acesas"),
            F("luminaire_label", {}, "label_photo", "after", "Etiqueta do produto instalado"),
            F("removed_items", {}, "removed_items_photo", "after", "Lâmpadas antigas retiradas"),
        ],
        docs=["certificate"],
        out=("Luminária LED de embutir 60x60", "un", 4, "ELE-001"),
        material=0,
    ),
    ServiceTemplate(
        "hvac",
        "SETA",
        "air_conditioning",
        "preventive_maintenance",
        "preventive",
        "Epsilon",
        "Manutenção preventiva (PMOC) dos {q} aparelhos split do {env}: limpeza, higienização e verificação.",
        ["backoffice", "salão de atendimento"],
        (2, 6),
        [
            ("Limpeza preventiva de split (evap. + cond.)", "un", "q", "HVAC-001"),
            ("Higienização com bactericida", "un", "q", "HVAC-002"),
            ("Verificação de pressões", "un", "q", "HVAC-003"),
        ],
        before=[F("ac_filter", {"dirty": True}, "equipment_photo", "before", "Filtro de ar sujo antes da limpeza")],
        after=[
            F("split_evaporator", {}, "equipment_photo", "after", "Evaporadora limpa"),
            F("ac_filter", {}, "equipment_photo", "after", "Filtro limpo"),
        ],
        out=("Pintura de paredes da sala", "m²", 30, "PIN-001"),
        material=0,
    ),
    ServiceTemplate(
        "outlets",
        "SETA",
        "electrical",
        "electrical_failure",
        "corrective",
        "Eta",
        "Substituir {q} tomadas danificadas no {env}, uma com sinais de queima.",
        ["salão de atendimento", "backoffice"],
        (2, 8),
        [("Tomada 2P+T 10A com placa", "un", "q", "ELE-004"), ("Mão de obra substituição de tomada", "un", "q", "ELE-005")],
        before=[F("outlets", {"burned": True}, "room_before_photo", "before", "Tomada com marcas de queima")],
        after=[F("outlets", {}, "room_after_photo", "after", "Tomadas novas instaladas")],
        out=("Disjuntor DIN 20A", "un", 2, "ELE-006"),
        material=0,
    ),
    ServiceTemplate(
        "sink",
        "SETA",
        "plumbing",
        "leak",
        "corrective",
        "Theta",
        "Vazamento no sifão da pia da {env}. Trocar o sifão.",
        ["kitchen", "cozinha dos funcionários"],
        (1, 3),
        [("Visita técnica", "vb", 1, "GER-001"), ("Sifão PVC para pia", "un", 1, "HID-001"), ("Mão de obra hidráulica", "h", "q", "HID-003")],
        before=[F("under_sink_leak", {}, "room_before_photo", "before", "Sifão vazando sob a pia")],
        after=[],
        out=("Registro de pressão 3/4", "un", 2, "HID-002"),
        moment="quote",
        material=2,
    ),
    ServiceTemplate(
        "door",
        "SETA",
        "metalwork",
        "mechanical_failure",
        "corrective",
        "Zeta",
        "Porta do {env} não fecha sozinha: trocar a mola aérea e regular.",
        ["backoffice", "treasury"],
        (1, 1),
        [("Mola aérea nova", "un", 1, "SER-001"), ("Instalação de mola aérea", "un", 1, "SER-002"), ("Regulagem de porta", "un", 1, "SER-003")],
        before=[],
        after=[
            F("door_closer", {}, "room_after_photo", "after", "Porta com mola aérea instalada"),
            F("door_closer", {"close": True}, "equipment_photo", "after", "Mola aérea em detalhe"),
        ],
        out=("Pintura da porta", "m²", 4, "PIN-001"),
        before_applicable=False,
    ),
    ServiceTemplate(
        "camera",
        "SISR",
        "cctv",
        "degraded_image",
        "corrective",
        "Beta",
        "Câmera do {env} com imagem desfocada: limpeza e ajuste de foco.",
        ["self_service", "parking", "corridor"],
        (1, 1),
        [("Visita técnica e deslocamento", "vb", 1, "SIS-001"), ("Limpeza e ajuste de foco da câmera", "un", 1, "CFTV-001")],
        before=[F("cctv_frame", {"blur": 9, "cctv": True}, "cctv_screen_photo", "before", "Imagem da câmera desfocada")],
        after=[
            F("cctv_frame", {"cctv": True}, "cctv_screen_photo", "after", "Imagem da câmera nítida após o ajuste"),
            F("bullet_camera_wall", {}, "equipment_photo", "after", "Câmera instalada na parede"),
        ],
        out=("Cabo UTP cat6 novo", "m", 25, "CFTV-003"),
        replacement=("Câmera IP bullet nova 4MP", "un", 1, "CFTV-002"),
    ),
    ServiceTemplate(
        "sensor",
        "SISR",
        "alarm",
        "false_alarm",
        "corrective",
        "Kappa",
        "Sensor IVP da {env} com disparos falsos: substituir o sensor e testar a zona.",
        ["treasury", "back_office"],
        (1, 1),
        [
            ("Visita técnica", "vb", 1, "SIS-001"),
            ("Sensor IVP com fio", "un", 1, "ALA-002"),
            ("Mão de obra substituição de sensor", "un", 1, "ALA-003"),
        ],
        before=[F("motion_sensor", {"old": True}, "equipment_photo", "before", "Sensor antigo amarelado")],
        after=[
            F("motion_sensor", {}, "equipment_photo", "after", "Sensor novo instalado"),
            F("keypad_closeup", {"lcd": "ZONA OK"}, "alarm_panel_photo", "after", "Teclado indicando zona OK"),
        ],
        docs=["certificate"],
        out=("Botão de pânico sem fio", "un", 1, "ALA-004"),
    ),
    ServiceTemplate(
        "preventive",
        "SISR",
        "cctv_and_alarm",
        "preventive_maintenance",
        "preventive",
        "Iota",
        "Preventiva semestral do sistema de segurança da agência: teste das {q} câmeras e dos sensores do alarme, com relatório.",
        ["agência inteira"],
        (4, 12),
        [
            ("Visita técnica e deslocamento", "vb", 1, "SIS-001"),
            ("Teste preventivo de câmera", "un", "q", "CFTV-007"),
            ("Teste preventivo de sensor", "un", "q", "ALA-001"),
        ],
        before=[],
        after=[
            F("monitor_grid", {"grid": True}, "cctv_screen_photo", "after", "Monitor do NVR com as câmeras funcionando"),
            F("alarm_panel", {}, "alarm_panel_photo", "after", "Central de alarme pronta"),
        ],
        docs=["report"],
        out=("Câmera IP bullet nova 4MP", "un", 1, "CFTV-002"),
        before_applicable=False,
        material=1,
    ),
]

# defeito → apontamento esperado (checklist é tratado à parte)
DEFECTS = [
    "out_of_scope",
    "replacement",
    "quantity",
    "price",
    "duplicate",
    "spreadsheet",
    "vague",
    "inconsistent",
    "does_not_match",
    "no_before",
    "no_after",
    "unreadable",
    "reused",
    "date_before",
    "checklist",
]
WEIGHTS = {
    "out_of_scope": 12,
    "replacement": 14,
    "quantity": 10,
    "price": 12,
    "duplicate": 8,
    "spreadsheet": 4,
    "vague": 3,
    "inconsistent": 3,
    "does_not_match": 11,
    "no_before": 10,
    "no_after": 14,
    "unreadable": 5,
    "reused": 6,
    "date_before": 4,
    "checklist": 6,
}
UNEXPECTED_SYMPTOM = {"SETA": ["false_alarm", "no_image", "device_inoperative"], "SISR": ["leak", "finish_wear", "moisture_infiltration"]}


def requirements(m: ServiceTemplate) -> list:
    return CFG.checklists.requirements(m.category, m.maintenance, m.moment)


def result_evidence(f: dict) -> bool:
    return f["moment"] == "after" and f["category"] in ("room_after_photo", "cctv_screen_photo")


def complete_checklist(m: ServiceTemplate, photos: list[dict], docs: list[str] | None = None) -> bool:
    docs = m.docs if docs is None else docs
    cats = (
        {f["category"] for f in photos}
        | {"quote_doc"}
        | {"completion_certificate_doc" if d == "certificate" else "technical_report_doc" for d in docs}
    )
    return all(any(c.value in cats for c in r.accepted) for r in requirements(m))


def vary(img: Image.Image, rnd: random.Random, strength: float, mirror: bool = True) -> Image.Image:
    """Variação de "fotógrafo". mirror=False para fotos reais: espelhar inverteria logos e letreiros."""
    from PIL import ImageEnhance, ImageOps

    w, h = img.size
    if rnd.random() < 0.5 and mirror:
        img = ImageOps.mirror(img)
    z = 1 + rnd.uniform(0.05, 0.45) * strength
    cw, ch = w / z, h / z
    x0, y0 = rnd.uniform(0, w - cw), rnd.uniform(0, h - ch)
    img = img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((w, h), Image.BICUBIC)
    ang = rnd.uniform(-9, 9) * strength
    img = img.rotate(ang, resample=Image.BICUBIC, fillcolor=(60, 60, 60)).crop((40, 30, w - 40, h - 30)).resize((w, h))
    img = ImageEnhance.Brightness(img).enhance(rnd.uniform(0.85, 1.12))
    img = ImageEnhance.Contrast(img).enhance(rnd.uniform(0.85, 1.15))
    return ImageEnhance.Color(img).enhance(rnd.uniform(0.8, 1.2))


def context(img: Image.Image, rnd: random.Random) -> Image.Image:
    """Detalhes de ambiente que distinguem fotos reais do mesmo tipo de equipamento: etiqueta de patrimônio, cabo
    aparente, mancha na parede, sombra. Usado quando só variar enquadramento não basta (cenas 2D muito parecidas)."""
    from PIL import ImageDraw, ImageFilter

    img = img.copy()
    w, h = img.size
    d = ImageDraw.Draw(img, "RGBA")
    # sombra lateral (luz de janela)
    side = rnd.choice([0, 1])
    for i in range(60):
        x = int(i * w * 0.006) if side == 0 else w - int(i * w * 0.006)
        d.line([(x, 0), (x, h)], fill=(0, 0, 0, max(0, 70 - i)), width=int(w * 0.006) + 1)
    # cabo aparente
    y = rnd.uniform(0.1, 0.9) * h
    pts = [(0, y)] + [(w * k / 5, y + rnd.uniform(-0.12, 0.12) * h) for k in range(1, 6)]
    d.line(pts, fill=rnd.choice([(245, 245, 240, 255), (40, 40, 40, 255), (30, 60, 150, 255)]), width=int(h * 0.012), joint="curve")
    # manchas e marcas na parede
    for _ in range(rnd.randint(3, 7)):
        cx, cy, r = rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(0.02, 0.08) * w
        d.ellipse((cx - r, cy - r * 0.7, cx + r, cy + r * 0.7), fill=(90, 80, 60, rnd.randint(18, 45)))
    # etiqueta de patrimônio
    ex, ey = rnd.uniform(0.05, 0.75) * w, rnd.uniform(0.05, 0.8) * h
    ew, tag_h = 0.2 * w, 0.075 * h
    d.rectangle((ex, ey, ex + ew, ey + tag_h), fill=(250, 250, 250, 255), outline=(30, 30, 30, 255), width=2)
    d.rectangle((ex, ey, ex + ew * 0.28, ey + tag_h), fill=(20, 60, 140, 255))
    for k in range(14):
        bx = ex + ew * 0.33 + k * ew * 0.045
        d.rectangle((bx, ey + tag_h * 0.2, bx + ew * rnd.choice([0.01, 0.02, 0.03]), ey + tag_h * 0.8), fill=(20, 20, 20, 255))
    return img.filter(ImageFilter.GaussianBlur(0.6))


# ============================================================================ geração
class ValidationGenerator:
    """Gera chamados a partir dos modelos de serviço, com defeitos sorteados e gabarito pela régua.

    prefix/dataset/branches/day0 permitem gerar outros conjuntos com a mesma mecânica (ex.: `itau`).
    realistic=True é para fotos reais/fotorrealistas: não espelha (logos e letreiros ficariam invertidos) e não desenha
    os detalhes de `context()` por cima (cabo, manchas, etiqueta), que dariam cara de montagem à foto."""

    def __init__(
        self,
        n_per_template: int,
        seed: int = 2026,
        prefix: str = "0100",
        dataset: str = "validation",
        branches: list[tuple[str, str]] | None = None,
        day0: date = date(2026, 10, 15),  # depois de todo o conjunto de demonstração
        realistic: bool = False,
    ):
        self.n = n_per_template
        self.rnd = random.Random(seed)
        self.prefix, self.dataset, self.branches, self.day0, self.realistic = prefix, dataset, branches or BRANCHES, day0, realistic
        self.hashes: list[tuple[str, tuple]] = []  # (id, hash) de fotos de chamados já gerados
        self.photos_per_template: dict[str, list[tuple[str, Path, date]]] = {}
        self.seq = 0

    def index_existing(self) -> None:
        for base in (ROOT / "tickets", ROOT / "history"):
            for p in base.glob("*/attachments/*.jpg"):
                self.hashes.append((p.parent.parent.name, hashes_with_crops(p, CFG.rubric.hash_crops)))

    def _closest_distance(self, tid: str, hs: list) -> int:
        """Menor distância a qualquer foto de outro chamado, comparando como o produto compara (com recortes, nos dois sentidos)."""
        return min(
            (min(min(distance(hs[0], y) for y in other), min(distance(other[0], y) for y in hs)) for c, other in self.hashes if c != tid),
            default=128,
        )

    def unique_photo(self, tid: str, scene: str, kw: dict, seed: int) -> Image.Image:
        """Renderiza e garante que não fique parecida demais com foto de outro chamado (evita falso reaproveitamento).
        Cenas 2D (tomada, sensor, porta...) variam pouco; a cada tentativa o "fotógrafo" muda mais: espelha, aproxima,
        inclina e muda a luz, como fotos reais de celular de chamados diferentes. Se nenhuma tentativa passar da margem,
        fica a mais distante de todas."""
        margin = CFG.rubric.hash_max_distance + 8
        best: tuple[int, Image.Image, list] | None = None
        for attempt in range(14):
            s = seed + 7919 * attempt
            r = random.Random(s)
            try:
                base = render_scene(scene, {**kw, "seed": s, "framing": s}, s)
            except real_photos.PhotoShortage:
                if best is None:
                    raise
                break  # modo strict: acabaram as fotos para novas tentativas; fica a melhor até aqui
            img = vary(base, r, strength=min(1.0, 0.35 + 0.1 * attempt), mirror=not self.realistic)
            if attempt >= 3 and not self.realistic:
                img = context(img, r)
            tmp = Path(tempfile.gettempdir()) / "_val.jpg"
            img.save(tmp, quality=85)
            hs = hashes_with_crops(tmp, CFG.rubric.hash_crops)
            d = self._closest_distance(tid, hs)
            if best is None or d > best[0]:
                best = (d, img, hs)
            if d > margin or real_photos.MODE == "record":  # record: conta só a 1ª tentativa (o desenho repete mais que foto)
                break
        d, img, hs = best
        if d <= CFG.rubric.hash_max_distance:
            print(f"  aviso: {tid} {scene} ficou a {d} de outra foto (limite {CFG.rubric.hash_max_distance})")
        self.hashes.append((tid, hs))
        return img

    def generate(self) -> list[dict]:
        summary = []
        order = [(m, k) for k in range(self.n) for m in MODELS]
        for i, (m, k) in enumerate(order):
            self.seq += 1
            tid = f"{self.prefix}{self.seq:04d}"
            opening = self.day0 + timedelta(days=i // 3)
            summary.append(self.one_ticket(tid, m, k, opening))
        return summary

    def draw_defects(self, m: ServiceTemplate, k: int) -> list[str]:
        if k == 0:  # o primeiro de cada modelo sai limpo, para ter aprovações garantidas
            return []
        n = self.rnd.choices([0, 1, 2, 3, 4], weights=[14, 30, 28, 18, 10])[0]
        possible = [d for d in DEFECTS if self._applicable(m, d)]
        chosen: list[str] = []
        while len(chosen) < n and possible:
            d = self.rnd.choices(possible, weights=[WEIGHTS[x] for x in possible])[0]
            chosen.append(d)
            possible.remove(d)
            if d == "checklist":  # devolvido no checklist: o resto não chega a ser avaliado
                return ["checklist"]
        return chosen

    def _applicable(self, m: ServiceTemplate, d: str) -> bool:
        if d == "replacement":
            return m.replacement is not None
        if d == "no_before":  # só quando o checklist continua completo sem a foto do antes (senão vira caso de checklist)
            return m.before_applicable and bool(m.before) and complete_checklist(m, m.after)
        if d == "no_after":  # idem, sem a foto que prova o resultado
            rest = [f for f in m.before + m.after if not result_evidence(f)]
            return m.moment == "execution" and len(rest) < len(m.before + m.after) and complete_checklist(m, rest) and m.name == "camera"
        if d == "quantity":
            return isinstance(m.items[m.material][2], str)
        if d == "vague":
            return m.replacement is None  # escopo vago + troca deixaria o gabarito ambíguo
        return True

    # ------------------------------------------------------------------ um chamado
    def one_ticket(self, tid: str, m: ServiceTemplate, k: int, opening: date) -> dict:
        rnd = random.Random(int(tid))
        defects = self.draw_defects(m, k)
        env = rnd.choice(m.environments)
        q = rnd.randint(*m.q)
        code, branch = rnd.choice(self.branches)
        submission = opening + timedelta(days=rnd.randint(2, 6))
        scope = m.scope.format(env=env, q=q)
        symptom = m.symptom
        optional: list[str] = []
        rubric = CFG.rubric

        # ---- itens
        items = []  # (desc, un, qtd, unit, rótulo)
        for desc, un, qt, lpu in m.items:
            qty = q if qt == "q" else qt
            ref = LPU_IDX[m.workstream][lpu][3]
            items.append([desc, un, qty, ref, {"classification": "compliant", "lpu": lpu, "findings": [], "optional": [], "qmax": None}])
        if "quantity" in defects:
            it = items[m.material]
            qmax = it[2]
            it[2] = qmax + max(1, round(qmax * rnd.uniform(0.25, 0.6)))
            it[4]["findings"].append("quantity_above_expected")
            it[4]["qmax"] = qmax
        if "price" in defects:
            it = rnd.choice([x for x in items if x[1] != "vb"] or items)
            it[3] = round(it[3] * rnd.uniform(1.2, 1.6), 2)
            it[4]["findings"].append("price_above_reference")
        if "out_of_scope" in defects and m.out:
            d, un, qt, lpu = m.out
            items.append(
                [
                    d,
                    un,
                    qt,
                    LPU_IDX[m.workstream][lpu][3],
                    {"classification": "out_of_scope", "lpu": lpu, "findings": ["out_of_scope_item"], "optional": [], "qmax": None},
                ]
            )
        if "replacement" in defects and m.replacement:
            d, un, qt, lpu = m.replacement
            items.append(
                [
                    d,
                    un,
                    qt,
                    LPU_IDX[m.workstream][lpu][3],
                    {"classification": "to_justify", "lpu": lpu, "findings": ["unjustified_replacement"], "optional": [], "qmax": None},
                ]
            )
        if "duplicate" in defects:
            base = items[m.material if isinstance(m.items[m.material][2], str) else 0]
            items.append(
                [
                    base[0].replace(" com ", " c/ "),
                    base[1],
                    base[2],
                    base[3],
                    {"classification": "compliant", "lpu": base[4]["lpu"], "findings": ["duplicate_item"], "optional": [], "qmax": None},
                ]
            )
        if "vague" in defects:
            scope = m.vague.format(env=env)
        if "inconsistent" in defects:
            symptom = rnd.choice(UNEXPECTED_SYMPTOM[m.workstream])

        case = {
            "id": tid,
            "category": m.category,
            "symptom": symptom,
            "workstream": m.workstream,
            "maintenance_type": m.maintenance,
            "moment": m.moment,
            "branch": (code, branch, env),
            "supplier": m.supplier,
            "quote_number": f"{m.supplier[:3].upper()}-V{tid[-4:]}",
            "dates": {
                "opening": opening.isoformat(),
                "supplier_submission": submission.isoformat(),
                "manager_review": (submission + timedelta(days=1)).isoformat(),
            },
            "scope": scope,
            "items": [tuple(x) for x in items],
        }
        total = round(sum(x[2] * x[3] for x in items), 2)
        ticket_value = total
        if "spreadsheet" in defects:
            if rnd.random() < 0.5:
                ticket_value = round(total * rnd.uniform(0.8, 0.92), 2)
            else:
                case["spreadsheet"] = {"symptom": rnd.choice([s for s in UNEXPECTED_SYMPTOM["SETA"] + UNEXPECTED_SYMPTOM["SISR"] if s != symptom])}

        # ---- pasta e planilha
        folder = ROOT / "tickets" / tid / "attachments"
        folder.mkdir(parents=True, exist_ok=True)
        spreadsheet = folder / f"Orcamento_{case['quote_number']}.xlsx"
        make_xlsx(spreadsheet, case)
        attachments_meta = [attachment_meta(spreadsheet, case["dates"]["supplier_submission"])]
        rot = {
            spreadsheet.name: {"category": "quote_doc", "moment": "undetermined", "matches_scope": True, "readable": True, "description": "Orçamento"}
        }

        # ---- fotos
        photos = [dict(f) for f in m.before + m.after]
        if "no_before" in defects:
            photos = [f for f in photos if f["moment"] != "before"]
        if "no_after" in defects:
            photos = [f for f in photos if not result_evidence(f)]
        docs = list(m.docs)
        missing: list[str] = []
        if "checklist" in defects:
            req = [r for r in requirements(m) if r.id != "quote"]
            target = rnd.choice(req)
            accepted = {c.value for c in target.accepted}
            photos = [f for f in photos if f["category"] not in accepted]
            docs = [d for d in docs if ("completion_certificate_doc" if d == "certificate" else "technical_report_doc") not in accepted]
            missing = [
                r.id
                for r in requirements(m)
                if r.id != "quote"
                and not any(
                    c.value
                    in {f["category"] for f in photos}
                    | {"completion_certificate_doc" if d == "certificate" else "technical_report_doc" for d in docs}
                    for c in r.accepted
                )
            ]
        cctv = _cctv(rnd)
        hour = 8
        photo_day = {"before": opening + timedelta(days=1), "after": submission - timedelta(days=1)}
        for j, f in enumerate(photos):
            kw = dict(f["kw"])
            if kw.pop("cctv", False):
                kw.update(scene=cctv["scene"], label=cctv["label"], stamp=f"{photo_day[f['moment']]:%d/%m/%Y} 1{j}:0{j}:00")
            if kw.pop("grid", False):
                kw["tiles"] = [(rnd.choice(["atm", "corridor", "parking", "office"]), f"CAM {c + 1:02d}") for c in range(min(q, 9))]
                kw["cols"] = kw["rows"] = 3 if q > 4 else 2
            if f["scene"] in ("backoffice", "ceiling_view"):
                kw.setdefault("layout", int(tid))
            if f["scene"] == "door_closer" or f["scene"] == "outlets":
                pass
            name = f"IMG_{photo_day[f['moment']]:%Y%m%d}_{hour + j:02d}{rnd.randint(10, 59)}{rnd.randint(10, 59)}.jpg"
            img = self.unique_photo(tid, f["scene"], kw, int(tid[-4:]) * 31 + j)
            exif_date = f"{photo_day[f['moment']]:%Y:%m:%d} {hour + j:02d}:15:00"
            save_jpg(img, folder / name, exif_date, j)
            attachments_meta.append(attachment_meta(folder / name, case["dates"]["supplier_submission"]))
            rot[name] = {"category": f["category"], "moment": f["moment"], "matches_scope": True, "readable": True, "description": f["description"]}
        # defeitos que acrescentam fotos
        if "does_not_match" in defects:
            scene, desc = rnd.choice(OTHER_ROOMS)
            name = f"IMG_{submission:%Y%m%d}_17{rnd.randint(10, 59)}00.jpg"
            save_jpg(self.unique_photo(tid, scene, {}, int(tid) % 9973 + 501), folder / name, f"{submission:%Y:%m:%d} 17:20:00", 9)
            attachments_meta.append(attachment_meta(folder / name, case["dates"]["supplier_submission"]))
            rot[name] = {
                "category": "other" if scene != "facade" else "room_after_photo",
                "moment": "after" if scene == "facade" else "undetermined",
                "matches_scope": False,
                "readable": True,
                "description": desc,
            }
        if "unreadable" in defects:
            name = f"IMG_{submission:%Y%m%d}_18{rnd.randint(10, 59)}00.jpg"
            base = render_scene(rnd.choice(["door_closer", "outlets", "rack"]), {"seed": int(tid)}, int(tid))
            save_jpg(illegible(base, seed=int(tid)), folder / name, f"{submission:%Y:%m:%d} 18:00:00", 3)
            attachments_meta.append(attachment_meta(folder / name, case["dates"]["supplier_submission"]))
            rot[name] = {
                "category": "other",
                "moment": "undetermined",
                "matches_scope": None,
                "readable": False,
                "description": "Foto escura e tremida",
            }
        if "reused" in defects:
            sources = [f for f in self.photos_per_template.get(m.name, []) if f[2] <= submission and f[0] != tid]
            if sources:
                origin_id, origin, _ = rnd.choice(sources)
                name = f"WhatsApp Image {submission:%Y-%m-%d} at 15.{rnd.randint(10, 59)}.{rnd.randint(10, 59)}.jpeg"
                img = Image.open(origin).convert("RGB")
                w, h = img.size
                img.crop((int(w * 0.02), int(h * 0.02), int(w * 0.98), int(h * 0.98))).resize((1200, 900)).save(folder / name, quality=70)
                attachments_meta.append(attachment_meta(folder / name, case["dates"]["supplier_submission"]))
                r0 = origin_label(origin_id, origin.name)
                rot[name] = {**r0, "reused_from": f"{origin_id}/{origin.name}"}
            else:
                defects.remove("reused")
        if "date_before" in defects:
            target = next((n for n, r in rot.items() if n.startswith("IMG_") and r["readable"] and r["matches_scope"]), None)
            if target:
                img = Image.open(folder / target).convert("RGB")
                old = opening - timedelta(days=rnd.randint(20, 120))
                save_jpg(img, folder / target, f"{old:%Y:%m:%d} 10:00:00", 1)
            else:
                defects.remove("date_before")
        for d in docs:
            name = f"IMG_{submission:%Y%m%d}_19{len(rot):02d}00.jpg"
            if d == "certificate":
                img = scenes.paper_photo(
                    "TERMO DE CONCLUSÃO DE SERVIÇO",
                    [
                        ("Chamado", tid),
                        ("Agência", f"{branch} ({code})"),
                        ("Fornecedor", SUPPLIER[m.supplier][0][:32]),
                        ("Serviço", scope[:34] + "…"),
                        ("Data", f"{submission:%d/%m/%Y}"),
                    ],
                    seed=int(tid) % 997,
                )
                cat, desc = "completion_certificate_doc", "Termo de conclusão assinado"
            else:
                img = scenes.paper_photo(
                    "RELATÓRIO DE MANUTENÇÃO PREVENTIVA",
                    [
                        ("Chamado", tid),
                        ("Agência", f"{branch} ({code})"),
                        ("Câmeras testadas", f"{q} de {q} — OK"),
                        ("Data", f"{submission:%d/%m/%Y}"),
                    ],
                    seed=int(tid) % 991,
                )
                cat, desc = "technical_report_doc", "Relatório de preventiva"
            save_jpg(photograph(finish(img, seed=int(tid) % 89), int(tid), paper=True), folder / name, f"{submission:%Y:%m:%d} 19:00:00", 5)
            attachments_meta.append(attachment_meta(folder / name, case["dates"]["supplier_submission"]))
            rot[name] = {"category": cat, "moment": "after", "matches_scope": True, "readable": True, "description": desc}

        # guarda fotos "boas" deste chamado como fonte de reaproveitamento para os próximos do mesmo modelo
        good = [
            folder / n for n, r in rot.items() if n.startswith("IMG_") and r["readable"] and r["matches_scope"] and not r["category"].endswith("_doc")
        ]
        self.photos_per_template.setdefault(m.name, []).extend((tid, p, submission) for p in good)
        _LABELS[(tid,)] = rot

        # ---- chamado.json
        ticket = {
            "ticket_id": tid,
            "workstream": m.workstream,
            "maintenance_type": m.maintenance,
            "moment": m.moment,
            "category": m.category,
            "symptom": symptom,
            "branch": {"code": code, "name": branch, "environment": env},
            "supplier": {"name": SUPPLIER[m.supplier][0], "cnpj": SUPPLIER[m.supplier][1]},
            "requested_scope": scope,
            "quoted_value": ticket_value,
            "dates": case["dates"],
            "status": "forwarded_to_backoffice",
            "origin": "dataset",
            "dataset": self.dataset,
            "manager": {"first_check": "forwarded", "note": ""},
            "attachments": attachments_meta,
        }
        (folder.parent / "ticket.json").write_text(json.dumps(ticket, ensure_ascii=False, indent=2), encoding="utf-8")

        # ---- gabarito: aplica a régua aos defeitos
        kinds: list[str] = []
        if "checklist" in defects:
            recommendation, score, grades, confidence = "checklist_returned", None, None, None
        else:
            mapping = {
                "vague": "vague_scope",
                "inconsistent": "inconsistent_scope",
                "spreadsheet": "spreadsheet_mismatch",
                "does_not_match": "photo_mismatch",
                "no_before": "missing_before_photo",
                "no_after": "missing_after_photo",
                "unreadable": "unreadable_photo",
                "reused": "reused_photo",
                "date_before": "photo_dated_before",
            }
            kinds = sorted({mapping[d] for d in defects if d in mapping} | {a for x in items for a in x[4]["findings"]})
            if "vague" in defects:
                optional += ["unjustified_replacement"]
            if "does_not_match" in defects and m.moment == "execution":
                pass
            scorer = ScoreCalculator(rubric)
            res = scorer.compute([scorer.finding(t, "") for t in kinds])
            recommendation, score, confidence = res.recommendation.value, res.score, res.confidence.value
            grades = res.grades.model_dump()
        at_issue = 0.0
        for _desc, _unit_label, qty, unit, r in items:
            tps = r["findings"]
            if any(rubric.finding_types[t].amount_at_issue.value == "item" for t in tps):
                at_issue += qty * unit
            else:
                exc = 0.0
                if "price_above_reference" in tps:
                    exc += (unit - LPU_IDX[m.workstream][r["lpu"]][3]) * qty
                if "quantity_above_expected" in tps:
                    exc += (qty - r["qmax"]) * unit
                at_issue += min(exc, qty * unit)
        gt = {
            "ticket_id": tid,
            "dataset": self.dataset,
            "service_template": m.name,
            "defects": defects,
            "workstream": m.workstream,
            "moment": m.moment,
            "maintenance_type": m.maintenance,
            "category": m.category,
            "symptom": symptom,
            "before_applicable": m.before_applicable,
            "quoted_value": ticket_value,
            "amount_at_issue": round(at_issue, 2),
            "items": [
                {
                    "n": n,
                    "description": d,
                    "unit": un,
                    "quantity": qt,
                    "unit_value": u,
                    "total_value": round(qt * u, 2),
                    "classification": r["classification"],
                    "lpu_code": r["lpu"],
                    "reference_price": LPU_IDX[m.workstream][r["lpu"]][3],
                    "findings": r["findings"],
                    "optional_findings": r["optional"],
                    "expected_quantity_max": r["qmax"],
                }
                for n, (d, un, qt, u, r) in enumerate(items, 1)
            ],
            "attachments": rot,
            "checklist_ok": "checklist" not in defects,
            "missing": missing,
            "findings": kinds,
            "optional": optional,
            "grades": grades,
            "score": score,
            "recommendation": recommendation,
            "confidence": confidence,
        }
        (ROOT / "ground_truth" / f"{tid}.json").write_text(json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"id": tid, "model": m.name, "defects": defects, "recommendation": recommendation, "score": score}


_LABELS: dict = {}


def origin_label(tid: str, name: str) -> dict:
    return dict(_LABELS[(tid,)][name])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8, help="chamados por modelo de serviço (10 modelos)")
    a = ap.parse_args()
    for p in list((ROOT / "tickets").glob("0100*")):
        shutil.rmtree(p)
    for p in (ROOT / "ground_truth").glob("0100*.json"):
        p.unlink()
    g = ValidationGenerator(a.n)
    g.index_existing()
    summary = g.generate()
    from collections import Counter

    print(f"{len(summary)} chamados de validação em {ROOT / 'tickets'}")
    print("recomendações esperadas:", dict(Counter(r["recommendation"] for r in summary)))
    print("defeitos injetados:", dict(Counter(d for r in summary for d in r["defects"])))
