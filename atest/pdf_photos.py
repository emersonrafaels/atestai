"""Fotos embutidas em PDF: viram anexos de foto, com a página e o texto ao lado (pergunta e resposta).

Na SISR, boa parte dos fornecedores manda um relatório em PDF no formato checklist, sem fotos soltas: cada pergunta
("O equipamento estava vandalizado?"), a resposta marcada (Sim/Não) e a foto que a demonstra. Sem extrair essas fotos, o
checklist mínimo devolvia o chamado (nenhum anexo de foto), a análise das fotos não tinha o que analisar e a checagem de
foto reaproveitada não as via.

Cada foto extraída é gravada ao lado do PDF, em attachments/ (`<pdf>_p01_foto01.jpg`), com um manifesto
(`<pdf>.fotos.json`) que serve de cache: a extração só roda de novo se o PDF mudar. Ficam de fora as imagens pequenas
(logo, ícone, caixa de marcação) e as repetidas (a logo em todas as páginas). JPEG embutido é gravado como está (mantém o
EXIF, que a checagem de data usa).

O texto ao lado vem da posição na página: as linhas logo acima da foto (pergunta, resposta, observação), mais as que
estão na mesma altura, à direita ou à esquerda dela.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .observability import event

MANIFEST_VERSION = 1
MIN_SIDE_PX = 160  # imagem menor que isso é logo, ícone ou caixa de marcação
MIN_DRAWN_PT = 50  # desenhada na página com menos de ~1,8 cm de lado: idem
CONTEXT_MAX_CHARS = 300
LINE_GAP_PT = 24  # linhas mais distantes que isso já são de outro bloco (outra pergunta, cabeçalho)
FIRST_LINE_PT = 70  # a primeira linha acima da foto precisa estar perto dela


@dataclass(frozen=True)
class PdfPhoto:
    """Foto extraída de um PDF: arquivo gravado, página (a partir de 1) e texto ao lado."""

    path: Path
    page: int
    context: str


def photo_file_name(pdf: Path, page: int, n: int) -> str:
    """Nome do arquivo da n-ésima foto da página (ex.: relatorio_p02_foto01.jpg)."""
    return f"{pdf.stem}_p{page:02d}_foto{n:02d}.jpg"


def manifest_path(pdf: Path) -> Path:
    return pdf.with_name(f"{pdf.name}.fotos.json")


def extract_pdf_photos(pdf: Path) -> list[PdfPhoto]:
    """Fotos do PDF, do cache quando o PDF não mudou; extrai e grava quando mudou ou é a primeira vez.

    Args:
        pdf: arquivo PDF (as fotos são gravadas na mesma pasta).

    Returns:
        As fotos na ordem das páginas; lista vazia se o PDF não tem fotos, não abre ou o pypdf não está instalado
        (registra um aviso no log).
    """
    if not pdf.is_file():
        return []
    stat = pdf.stat()
    key = {
        "version": MANIFEST_VERSION,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    cached = _from_manifest(pdf, key)
    if cached is not None:
        return cached
    try:
        found = _extract(pdf)
    except ImportError:
        event(
            "pdf_photos_unavailable",
            logging.WARNING,
            pdf=pdf.name,
            reason="pacote pypdf não instalado (pip install pypdf): as fotos do PDF não serão analisadas",
        )
        return []
    except (
        Exception
    ) as e:  # noqa: BLE001 — PDF corrompido ou fora do padrão: segue sem as fotos dele
        event("pdf_photos_failed", logging.WARNING, pdf=pdf.name, error=str(e)[:300])
        return []
    photos: list[PdfPhoto] = []
    try:
        for page, n, data, context in found:
            target = pdf.with_name(photo_file_name(pdf, page, n))
            target.write_bytes(data)
            photos.append(PdfPhoto(target, page, context))
        manifest_path(pdf).write_text(
            json.dumps(
                {
                    **key,
                    "photos": [
                        {"file": p.path.name, "page": p.page, "context": p.context}
                        for p in photos
                    ],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
    except (
        OSError
    ) as e:  # pasta sem permissão de escrita: segue sem as fotos (não dá para servi-las ao painel)
        event("pdf_photos_failed", logging.WARNING, pdf=pdf.name, error=str(e)[:300])
        return []
    if photos:
        event("pdf_photos_extracted", pdf=pdf.name, photos=len(photos))
    return photos


def _from_manifest(pdf: Path, key: dict) -> list[PdfPhoto] | None:
    """Fotos do manifesto, se ele é deste mesmo PDF (tamanho e data) e todos os arquivos ainda existem."""
    try:
        data = json.loads(manifest_path(pdf).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if any(data.get(k) != v for k, v in key.items()):
        return None
    photos = [
        PdfPhoto(pdf.with_name(p["file"]), int(p["page"]), p.get("context", ""))
        for p in data.get("photos", [])
    ]
    return photos if all(p.path.is_file() for p in photos) else None


def _extract(pdf: Path) -> list[tuple[int, int, bytes, str]]:
    """(página, número da foto na página, JPEG, texto ao lado) de cada foto do PDF.

    Raises:
        ImportError: pypdf não instalado.
    """
    from PIL import Image
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    seen: set[str] = set()  # imagens já vistas (a logo se repete em todas as páginas)
    out: list[tuple[int, int, bytes, str]] = []
    for page_no, page in enumerate(reader.pages, 1):
        texts, draws = _layout(page)
        n = 0
        for img in page.images:
            try:
                data = img.data
                digest = hashlib.sha1(data).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                pil = img.image
                if min(pil.size) < MIN_SIDE_PX:
                    continue
                box = draws.get(Path(img.name).stem)
                if box and min(box[2], box[3]) < MIN_DRAWN_PT:
                    continue
                if not _is_jpeg(data):
                    buf = io.BytesIO()
                    pil.convert("RGB").save(buf, "JPEG", quality=90)
                    data = buf.getvalue()
                else:  # JPEG em CMYK ou escala de cinza abre normalmente; só confere que é legível
                    Image.open(io.BytesIO(data)).verify()
            except (
                Exception
            ):  # noqa: BLE001 — imagem embutida que não decodifica: ignora só ela
                continue
            n += 1
            out.append((page_no, n, data, _context(texts, box) if box else ""))
    return out


def _is_jpeg(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff"


def _layout(
    page,
) -> tuple[
    list[tuple[float, float, str]], dict[str, tuple[float, float, float, float]]
]:
    """Linhas de texto (x, y, texto) e caixa de cada imagem desenhada (nome → x, y, largura, altura), em pontos."""
    texts: list[tuple[float, float, str]] = []
    draws: dict[str, tuple[float, float, float, float]] = {}

    def on_text(text, cm, tm, font_dict, font_size):
        if text and text.strip():
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            texts.append((x, y, " ".join(text.split())))

    def on_operator(operator, operands, cm, tm):
        if operator == b"Do" and operands:
            # imagem desenhada: a matriz atual leva o quadrado unitário para a caixa na página
            w, h = abs(cm[0]) + abs(cm[2]), abs(cm[1]) + abs(cm[3])
            x, y = cm[4] + min(0, cm[2]), cm[5] + min(0, cm[1])
            draws[str(operands[0]).lstrip("/")] = (x, y, w, h)

    try:
        page.extract_text(visitor_text=on_text, visitor_operand_before=on_operator)
    except Exception:  # noqa: BLE001 — sem posição, as fotos saem sem o texto ao lado
        return [], {}
    return texts, draws


def _context(
    texts: list[tuple[float, float, str]], box: tuple[float, float, float, float]
) -> str:
    """Texto ao lado da foto: o bloco de linhas logo acima dela e as linhas na mesma altura (à direita ou à esquerda)."""
    x, y, w, h = box
    top = y + h
    # acima da foto, da mais próxima para a mais distante; para quando há um vão (outro bloco: outra pergunta, cabeçalho)
    above = sorted((t for t in texts if t[1] >= top - 2), key=lambda t: t[1])
    block: list[tuple[float, float, str]] = []
    last = top
    for t in above:
        if t[1] - last > (FIRST_LINE_PT if not block else LINE_GAP_PT):
            break
        block.append(t)
        last = t[1]
    beside = [
        t
        for t in texts
        if y - 2 <= t[1] < top - 2 and (t[0] >= x + w - 2 or t[0] < x - 20)
    ]
    lines = sorted(block + beside, key=lambda t: (-round(t[1]), t[0]))
    return " ".join(t[2] for t in lines)[:CONTEXT_MAX_CHARS].strip()
