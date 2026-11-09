"""Anexos → blocos de conteúdo da API (imagem, PDF) e metadados de integridade (hash perceptual, EXIF)."""

from __future__ import annotations

import io
import json
import threading
from datetime import datetime
from pathlib import Path

import imagehash
from PIL import ExifTags, Image, ImageFilter, ImageOps, ImageStat

from .domain import Attachment
from .providers import DocumentPart, ImagePart, Part, TextPart

Hashes = tuple[imagehash.ImageHash, imagehash.ImageHash]


def image(path: Path, max_side: int = 1568) -> ImagePart:
    """JPEG reduzido ao lado máximo aceito pelos modelos (menos tokens, mesmo conteúdo)."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return ImagePart(data=buf.getvalue(), mime="image/jpeg")


def attachment_parts(attachment: Attachment, max_side: int = 1568) -> list[Part]:
    """Rótulo de texto + conteúdo, em formato neutro de provedor. O rótulo permite ao modelo citar 'Anexo N'."""
    label = TextPart(f"--- Anexo {attachment.index}: {attachment.name} ({attachment.content_type}) ---")
    if attachment.is_image:
        return [label, image(attachment.path, max_side)]
    if attachment.content_type == "application/pdf":
        return [label, DocumentPart(data=attachment.path.read_bytes(), mime="application/pdf", title=attachment.name)]
    return [TextPart(f"--- Anexo {attachment.index}: {attachment.name} ({attachment.content_type}) — formato não enviado ao modelo ---")]


def compute_hashes(path: Path) -> Hashes:
    """Hashes perceptuais (phash, dhash) da foto inteira, já com a orientação do EXIF aplicada."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return imagehash.phash(img), imagehash.dhash(img)


def hashes_with_crops(path: Path, crops: list[float]) -> list[Hashes]:
    """Hashes da foto inteira e de recortes centrais (fração tirada de cada borda). Foto reenviada por WhatsApp, print
    de tela ou foto recortada perde as bordas, e o dhash é sensível a esse deslocamento: comparar também com os recortes
    da foto original pega a cópia sem afrouxar o limite de distância."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    w, h = img.size
    out = []
    for c in [0.0, *crops]:
        r = img.crop((int(w * c), int(h * c), int(w * (1 - c)), int(h * (1 - c)))) if c else img
        out.append((imagehash.phash(r), imagehash.dhash(r)))
    return out


class HashCache:
    """Hashes (com recortes) e detalhe de cada foto, calculados uma vez só: em memória e, se houver arquivo, em disco.
    A chave inclui tamanho e data de modificação do arquivo e os recortes usados, então foto alterada é recalculada.
    Em produção, o mesmo papel é de uma tabela no banco preenchida quando a foto chega."""

    def __init__(self, file: Path | None = None):
        self.file = file
        self.data: dict[str, dict] = {}
        self.changed = False
        self._lock = threading.Lock()  # o painel pode abrir execuções em paralelo
        if file and file.exists():
            try:
                self.data = json.loads(file.read_text())
            except (OSError, ValueError):
                self.data = {}

    def get(self, path: Path, crops: list[float]) -> tuple[list[Hashes], float]:
        """Hashes (foto inteira + recortes) e nível de detalhe da foto, calculando só se não estiverem no cache."""
        st = path.stat()
        key = f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{','.join(map(str, crops))}"
        if (item := self.data.get(key)) is None:
            hs = hashes_with_crops(path, crops)
            item = {"h": [[str(a), str(b)] for a, b in hs], "d": detail_level(path)}
            self.data[key] = item
            self.changed = True
        return [(imagehash.hex_to_hash(a), imagehash.hex_to_hash(b)) for a, b in item["h"]], item["d"]

    def save(self) -> None:
        """Grava o cache em disco, se houve mudança."""
        with self._lock:
            self._save()

    def _save(self) -> None:
        if self.file and self.changed:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(self.data))
            self.changed = False


def detail_level(path: Path) -> float:
    """Quantidade de detalhe (desvio das bordas numa miniatura em cinza). Foto escura ou tremida fica abaixo de ~8;
    foto normal de celular fica acima de ~12. Em foto sem detalhe o hash perceptual perde poder de distinção:
    duas fotos borradas diferentes viram hashes parecidos, então a régua exige distância bem menor nesses casos."""
    g = ImageOps.exif_transpose(Image.open(path)).convert("L")
    g.thumbnail((256, 256))
    return float(ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).stddev[0])


def distance(h1: Hashes, h2: Hashes) -> int:
    """Soma das distâncias de Hamming de phash e dhash (0 = idênticas; 128 = máximo)."""
    return int((h1[0] - h2[0]) + (h1[1] - h2[1]))


def exif_date(path: Path) -> datetime | None:
    """Data e hora em que a foto foi tirada, pelo EXIF; None se não houver."""
    try:
        exif = Image.open(path).getexif()
        text = exif.get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
        return datetime.strptime(text, "%Y:%m:%d %H:%M:%S") if text else None
    except (OSError, ValueError, TypeError):
        return None
