"""Fotos reais (ou fotorrealistas) no lugar das cenas desenhadas.

Coloque fotos em `data/real_photos/<chave>/` (jpg ou png) e regenere os conjuntos: cada cena do gerador passa a usar
uma foto dessa pasta em vez do desenho. A pasta pode receber:
- fotos reais de chamados antigos (o melhor dado de teste possível; tire nomes, placas e rostos antes), ou
- fotos fotorrealistas geradas por um modelo de imagem com `python generator/ai_photos.py` (usa a sua chave de API).

Regras:
- Cada foto da pasta é usada por UM só chamado (registro em `<pasta>/_usage.json`). Reusar a mesma foto em dois
  chamados criaria reaproveitamento de verdade, e o produto o apontaria. Os casos de reaproveitamento continuam sendo
  feitos de propósito pelo gerador, copiando a foto de outro chamado.
- Se a pasta da chave estiver vazia ou esgotada, o gerador volta para o desenho, passado pela simulação de câmera
  (no modo "strict", é erro).
- Etiquetas, o teclado da central e o texto das telas do CFTV ficam sempre desenhados: o texto (data, câmera, modelo)
  precisa bater com o chamado. A IMAGEM da câmera de CFTV pode ser foto (chaves `cctv_view__*`), com o texto por cima.

Perfis (`use_profile`):
- "default": `data/real_photos/`, estilo neutro, sem marca (conjuntos `demo` e `validation`);
- "itau": `data/real_photos_itau/`, com a identidade visual do Itaú (conjunto `itau`, `generator/build_itau_dataset.py`).
Modos: "fallback" (sem foto, usa o desenho), "strict" (sem foto, erro) e "record" (não usa foto: só conta o que seria
pedido, para saber quantas gerar).
"""

from __future__ import annotations

import atexit
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

DATA = Path(__file__).resolve().parent.parent / "data"
ROOT = DATA / "real_photos"
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALWAYS_DRAWN = {"cctv_frame", "monitor_grid", "luminaire_label", "keypad_closeup"}

# chave → descrição da cena (usada como pasta e como prompt do modelo de imagem)
CATALOG: dict[str, str] = {
    "backoffice": "a bank branch back office with grey office desks, black office chairs, computer monitors, cork board, "
    "suspended ceiling with fluorescent troffer lights, painted walls in good condition",
    "backoffice__painting": "a bank branch back office right after wall painting: freshly painted walls, a step ladder, "
    "paint buckets and a roller tray on a protective plastic sheet on the floor, desks pushed aside",
    "backoffice__stains": "a bank branch back office wall with a large damp stain, black mould and peeling paint near the ceiling",
    "backoffice__lights_off": "a bank branch back office seen from the door, old fluorescent ceiling troffers, "
    "several of them switched off or flickering, dim uneven lighting",
    "ceiling_view": "looking up at a suspended mineral-fibre ceiling of an office with recessed light fittings, clean and recently painted",
    "ceiling_view__stains": "looking up at a suspended office ceiling with yellow-brown water infiltration stains and mould on the tiles",
    "ceiling_view__led": "looking up at a suspended office ceiling with new square 60x60 LED panel lights switched on",
    "bathroom": "a small staff bathroom in a commercial building, white wall tiles, washbasin, toilet",
    "storage": "a small storage room with metal shelves full of cardboard boxes and archive boxes",
    "facade": "the street facade of a small Brazilian bank branch, glass door, ATM area, sidewalk, no brand logos visible",
    "dome_camera": "a white CCTV dome camera installed on a suspended office ceiling, seen from below",
    "bullet_camera_wall": "a white bullet CCTV camera mounted on an outdoor wall bracket with its cable in a conduit",
    "rack": "an open small network rack with an NVR recorder, a PoE switch, patch cables and a power strip",
    "workbench_camera": "a disassembled bullet CCTV camera on a technician's workbench with screwdrivers and a multimeter",
    "split_evaporator": "a wall-mounted split air conditioner indoor unit, clean, with the front cover closed, high on an office wall",
    "split_evaporator__dirty": "a wall-mounted split air conditioner indoor unit with the front cover open, very dirty dusty "
    "filters and stained louvers",
    "ac_filter": "a technician's hand holding a clean, freshly washed split air conditioner filter mesh",
    "ac_filter__dirty": "a technician's hand holding a split air conditioner filter mesh clogged with grey dust",
    "condenser": "a split air conditioner outdoor condenser unit on a wall bracket outside a building, with copper pipes insulated",
    "door_closer": "an interior wooden office door with an aluminium overhead door closer installed at the top",
    "door_closer__detail": "close-up of a newly installed aluminium overhead hydraulic door closer arm on top of a wooden door",
    "outlets": "close-up of new white Brazilian standard three-pin wall outlets (NBR 14136) on an office wall",
    "outlets__burned": "close-up of a Brazilian three-pin wall outlet with black burn marks and melted plastic around the pins",
    "breaker_panel": "an open electrical distribution board with rows of DIN-rail circuit breakers and coloured wires, office building",
    "under_sink_leak": "inside a cabinet under a sink: a white PVC drain trap dripping water, wet cabinet floor and a puddle",
    "valve": "a chrome water shut-off valve on a tiled bathroom wall",
    "alarm_panel": "a wall-mounted intrusion alarm control box with a keypad next to it in an office corridor",
    "motion_sensor": "a new white passive infrared motion sensor mounted in the corner of an office ceiling",
    "motion_sensor__old": "an old yellowed passive infrared motion sensor with a cracked cover mounted in a wall corner",
    "power_supply_box": "a small metal power supply box for a security system with a backup battery inside, door open",
    "panic_button": "a red panic button installed under the edge of a bank teller counter",
    "removed_items__tubes": "old removed fluorescent tubes and broken ceiling light fittings piled on the floor of a storage room",
    # fundo da imagem de câmera de CFTV (o rótulo da câmera e a data/hora são desenhados por cima)
    "cctv_view__atm": "frame from a ceiling-mounted wide-angle security camera looking down at a bank self-service ATM lobby "
    "with a row of ATMs, empty, fluorescent light",
    "cctv_view__corridor": "frame from a ceiling-mounted wide-angle security camera looking down an empty bank branch corridor",
    "cctv_view__parking": "frame from a wall-mounted wide-angle security camera overlooking a small outdoor parking lot of a bank "
    "branch with a few parked cars, no readable licence plates",
    "cctv_view__office": "frame from a ceiling-mounted wide-angle security camera looking down at an empty bank back office",
}

STYLE = (
    "Amateur smartphone photo taken by a maintenance technician during a service call in a Brazilian bank branch. "
    "Natural indoor lighting, slightly tilted handheld framing, realistic colors and textures, ordinary everyday quality. "
    "No people, no faces, no readable brand names or logos, no text overlays, no watermark. Scene: "
)

# --------------------------------------------------------------------------- perfil Itaú
STYLE_ITAU = (
    "Amateur smartphone photo taken by a maintenance technician during a service call inside an Itaú Unibanco bank branch "
    "in Brazil. The branch follows the Itaú visual identity: Itaú orange (#EC7000) and navy blue accents on signage, accent "
    "walls, partitions and furniture, white and light grey surfaces; where the scene naturally allows it (facade, self-service "
    "area, partitions, totems) the orange rounded-square Itaú logo is visible. Natural lighting, slightly tilted handheld "
    "framing, realistic colors and textures, ordinary everyday quality, photorealistic, not a 3D render. No people, no faces, "
    "no readable licence plates, no text overlays, no watermark. Scene: "
)
_ITAU_OVERRIDES: dict[str, str] = {
    "backoffice": "the staff back office of an Itaú branch: white desks, black chairs, computer monitors, a navy blue accent wall "
    "with a small orange Itaú logo, suspended ceiling with light fittings, walls in good condition",
    "backoffice__painting": "the staff back office of an Itaú branch right after wall painting: freshly painted white walls, an "
    "orange accent wall, a step ladder, paint buckets and a roller tray on a protective plastic sheet, desks pushed aside",
    "backoffice__stains": "a wall of the staff back office of an Itaú branch with a large damp stain, black mould and peeling "
    "paint near the ceiling, an orange Itaú partition visible at the edge of the frame",
    "backoffice__lights_off": "the staff back office of an Itaú branch seen from the door, old fluorescent ceiling troffers, "
    "several of them switched off, dim uneven lighting, orange and navy furniture",
    "ceiling_view": "looking up at the white suspended ceiling of an Itaú branch customer area with recessed light fittings, "
    "clean and recently painted, the top of an orange Itaú sign at the edge of the frame",
    "ceiling_view__stains": "looking up at the suspended ceiling of an Itaú branch with yellow-brown water infiltration stains and "
    "mould on the tiles, the top of an orange Itaú sign at the edge of the frame",
    "ceiling_view__led": "looking up at the suspended ceiling of an Itaú branch customer area with new square 60x60 LED panel "
    "lights switched on, the top of an orange Itaú sign at the edge of the frame",
    "facade": "the street facade of an Itaú bank branch in a Brazilian city: glass front, the orange Itaú logo above the "
    "entrance, self-service ATM lobby, sidewalk",
    "storage": "a small storage room in the back of an Itaú branch with metal shelves, archive boxes and a few orange Itaú "
    "promotional displays",
    "bathroom": "a small staff bathroom in an Itaú branch, white wall tiles, washbasin, toilet",
    "alarm_panel": "a wall-mounted intrusion alarm control box with a keypad next to it in a corridor of an Itaú branch, navy "
    "blue wall stripe",
    "door_closer": "an interior office door of an Itaú branch, with an orange Itaú door sign, and an aluminium overhead door "
    "closer installed at the top",
    "cctv_view__atm": "frame from a ceiling-mounted wide-angle security camera looking down at the self-service ATM lobby of an "
    "Itaú branch: a row of orange and grey Itaú ATMs, orange Itaú signage, empty, fluorescent light",
    "cctv_view__corridor": "frame from a ceiling-mounted wide-angle security camera looking down an empty corridor of an Itaú "
    "branch, navy and orange wall stripe",
    "cctv_view__office": "frame from a ceiling-mounted wide-angle security camera looking down at the empty staff back office of "
    "an Itaú branch, orange and navy furniture",
}
CATALOG_ITAU: dict[str, str] = {**CATALOG, **_ITAU_OVERRIDES}

PROFILES: dict[str, tuple[Path, str, dict[str, str]]] = {
    "default": (DATA / "real_photos", STYLE, CATALOG),
    "itau": (DATA / "real_photos_itau", STYLE_ITAU, CATALOG_ITAU),
}
MODES = ("fallback", "strict", "record")
MODE = "fallback"
PROFILE = "default"


class PhotoShortage(RuntimeError):
    """Modo strict: a pasta da cena não existe ou não tem mais foto livre."""

    def __init__(self, k: str):
        super().__init__(f"sem foto livre em {ROOT / k} (gere com: python generator/ai_photos.py --profile {PROFILE} --only {k})")
        self.key = k


def use_profile(name: str = "default", mode: str = "fallback") -> None:
    """Troca a biblioteca de fotos (pasta, estilo e catálogo do modelo de imagem) e o modo de uso."""
    global ROOT, STYLE, CATALOG, MODE, PROFILE, _ledger
    if name not in PROFILES or mode not in MODES:
        raise ValueError(f"perfil {name!r} ou modo {mode!r} desconhecido")
    if _ledger is not None:
        _ledger.save()
    ROOT, STYLE, CATALOG = PROFILES[name]
    MODE, PROFILE, _ledger = mode, name, None
    _requests.clear()


# modo record: chave → sementes pedidas ("any" = basta uma foto, para fundos que podem se repetir)
_requests: dict[str, set] = {}


def needs() -> dict[str, int]:
    """Modo record: quantas fotos cada chave precisa ter."""
    return {k: len(v) for k, v in sorted(_requests.items())}


def key(name: str, kw: dict) -> str:
    """Pasta de fotos de uma cena do gerador (a variante muda o que a foto precisa mostrar)."""
    v = ""
    if name == "backoffice":
        v = "painting" if kw.get("painting_gear") else "stains" if kw.get("stains") else "lights_off" if kw.get("dead") else ""
    elif name == "ceiling_view":
        v = "stains" if kw.get("stains") else "led" if kw.get("lights") == "led" else ""
    elif name in ("split_evaporator", "ac_filter"):
        v = "dirty" if kw.get("dirty") else ""
    elif name == "door_closer":
        v = "detail" if kw.get("close") else ""
    elif name == "outlets":
        v = "burned" if kw.get("burned") else ""
    elif name == "motion_sensor":
        v = "old" if kw.get("old") else ""
    elif name == "removed_items":
        v = kw.get("kind", "tubes")
    elif name == "cctv_view":
        v = kw.get("scene", "atm")
    return f"{name}__{v}" if v else name


class _UsageLedger:
    """Qual foto da pasta foi para qual (cena, semente); persistido para regenerações darem o mesmo resultado."""

    def __init__(self) -> None:
        self.file = ROOT / "_usage.json"
        self.usage: dict[str, str] = json.loads(self.file.read_text()) if self.file.exists() else {}
        self.shortfalls: Counter = Counter()
        self.changed = False
        atexit.register(self.save)

    def save(self) -> None:
        if self.changed:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(self.usage, indent=1, sort_keys=True))
            self.changed = False
        if self.shortfalls:
            print("fotos reais esgotadas (usado o desenho):", dict(self.shortfalls))
            self.shortfalls.clear()

    def catch(self, k: str, seed: int) -> Path | None:
        folder = ROOT / k
        if not folder.is_dir():
            if MODE == "strict":
                raise PhotoShortage(k)
            return None
        ident = f"{k}|{seed}"
        if ident in self.usage and (folder / self.usage[ident]).exists():
            return folder / self.usage[ident]
        used = {v for i, v in self.usage.items() if i.startswith(f"{k}|")}
        free = sorted(p.name for p in folder.iterdir() if p.suffix.lower() in EXTENSIONS and p.name not in used)
        if not free:
            if MODE == "strict":
                raise PhotoShortage(k)
            self.shortfalls[k] += 1
            return None
        self.usage[ident] = free[0]
        self.changed = True
        return folder / free[0]


_ledger: _UsageLedger | None = None


def real_photo(name: str, kw: dict, seed: int, size: tuple[int, int]) -> Image.Image | None:
    """Foto da pasta para esta cena, já no tamanho do conjunto (recorte central), ou None para usar o desenho."""
    global _ledger
    if name in ALWAYS_DRAWN:
        return None
    k = key(name, kw)
    if MODE == "record":
        _requests.setdefault(k, set()).add(seed)
        return None
    if not ROOT.exists():
        if MODE == "strict":
            raise PhotoShortage(k)
        return None
    _ledger = _ledger or _UsageLedger()
    path = _ledger.catch(k, seed)
    if path is None:
        return None
    return _load(path, size)


def background(name: str, kw: dict, seed: int, size: tuple[int, int]) -> Image.Image | None:
    """Foto de fundo que PODE se repetir entre chamados (ex.: quadros pequenos do mosaico do CFTV): escolhe pela semente,
    sem registrar uso. None se não houver foto (no modo strict, erro)."""
    k = key(name, kw)
    if MODE == "record":
        _requests.setdefault(k, set()).add("any")
        return None
    folder = ROOT / k
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTENSIONS) if folder.is_dir() else []
    if not files:
        if MODE == "strict":
            raise PhotoShortage(k)
        return None
    return _load(files[seed % len(files)], size)


def _load(path: Path, size: tuple[int, int]) -> Image.Image:
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return ImageOps.fit(img, size, Image.LANCZOS)


def status() -> dict[str, tuple[int, int]]:
    """chave → (fotos na pasta, já usadas)."""
    usage = json.loads((ROOT / "_usage.json").read_text()) if (ROOT / "_usage.json").exists() else {}
    out = {}
    for k in CATALOG:
        folder = ROOT / k
        n = sum(p.suffix.lower() in EXTENSIONS for p in folder.iterdir()) if folder.is_dir() else 0
        out[k] = (n, sum(i.startswith(f"{k}|") for i in usage))
    return out
