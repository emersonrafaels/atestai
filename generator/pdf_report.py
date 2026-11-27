"""PDF de relatório de atendimento no formato checklist da SISR: pergunta, resposta Sim/Não e foto que a demonstra.

Escrito à mão (sem dependências): texto em Helvetica (WinAnsi, com acentos) e fotos JPEG embutidas como estão
(DCTDecode), do jeito que os aplicativos de campo dos fornecedores geram. Usado por generator/build_salesforce_cases.py e
pelos testes da extração de fotos de PDF.

    from pdf_report import Question, render_report
    pdf = render_report("Relatório de Atendimento", header_lines, [Question("Estava vandalizado?", True, jpeg)])
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

PAGE_W, PAGE_H = 595, 842  # A4 em pontos
MARGIN = 50


@dataclass
class Question:
    """Uma pergunta do checklist, a resposta marcada e a foto que a demonstra (JPEG; None = sem foto)."""

    text: str
    answer: bool | None  # True = Sim, False = Não, None = N/A
    photo: bytes | None = None
    note: str = ""  # observação do técnico, embaixo da resposta


def _esc(text: str) -> bytes:
    """Texto de string PDF em WinAnsi (cp1252), com parênteses e barra escapados."""
    raw = text.encode("cp1252", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _wrap(text: str, size: float, width: float) -> list[str]:
    """Quebra o texto em linhas que cabem em `width` pontos (largura média da Helvetica ~0,5 do corpo)."""
    per_line = max(10, int(width / (size * 0.5)))
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > per_line:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


class _Page:
    def __init__(self) -> None:
        self.ops: list[bytes] = []
        self.images: list[tuple[str, bytes, int, int]] = (
            []
        )  # nome, jpeg, largura, altura (px)

    def text(
        self, x: float, y: float, s: str, size: float = 10, bold: bool = False
    ) -> None:
        font = b"/F2" if bold else b"/F1"
        self.ops.append(
            b"BT %s %.1f Tf %.1f %.1f Td (%s) Tj ET" % (font, size, x, y, _esc(s))
        )

    def line(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.ops.append(b"%.1f %.1f m %.1f %.1f l S" % (x0, y0, x1, y1))

    def image(self, jpeg: bytes, x: float, y: float, w: float, h: float) -> None:
        with Image.open(io.BytesIO(jpeg)) as im:
            px_w, px_h = im.size
        name = f"Im{len(self.images) + 1}"
        self.images.append((name, jpeg, px_w, px_h))
        self.ops.append(
            b"q %.1f 0 0 %.1f %.1f %.1f cm /%s Do Q" % (w, h, x, y, name.encode())
        )


def _logo() -> bytes:
    """Logo pequena do fornecedor (vai em todas as páginas: a extração de fotos deve ignorar)."""
    im = Image.new("RGB", (90, 30), (236, 112, 0))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def render_report(
    title: str,
    header: list[str],
    questions: list[Question],
    footer: list[str] | None = None,
    per_page: int = 2,
    photo_height: float = 230,
) -> bytes:
    """Gera o PDF: cabeçalho com a logo e os dados do atendimento, `per_page` perguntas por página (pergunta, resposta
    marcada, observação e foto embaixo) e o rodapé (assinatura) na última página.

    Args:
        title: título do relatório.
        header: linhas do cabeçalho (fornecedor, chamado, agência, data, técnico...).
        questions: as perguntas, na ordem.
        footer: linhas finais (ex.: assinatura do gerente).
        per_page: perguntas por página.
        photo_height: altura das fotos, em pontos.

    Returns:
        Os bytes do PDF.
    """
    logo = _logo()
    pages: list[_Page] = []
    chunks = [
        questions[i : i + per_page] for i in range(0, len(questions), per_page)
    ] or [[]]
    n = 0
    for k, chunk in enumerate(chunks):
        pg = _Page()
        pages.append(pg)
        pg.image(logo, MARGIN, PAGE_H - MARGIN - 30, 90, 30)
        pg.text(MARGIN + 105, PAGE_H - MARGIN - 12, title, 13, bold=True)
        pg.text(
            PAGE_W - MARGIN - 70,
            PAGE_H - MARGIN - 12,
            f"Página {k + 1}/{len(chunks)}",
            8,
        )
        y = PAGE_H - MARGIN - 50
        if k == 0:
            for line in header:
                pg.text(MARGIN, y, line, 9.5)
                y -= 14
            y -= 6
        pg.line(MARGIN, y, PAGE_W - MARGIN, y)
        y -= 22
        for q in chunk:
            n += 1
            for i, line in enumerate(_wrap(f"{n}. {q.text}", 11, PAGE_W - 2 * MARGIN)):
                pg.text(MARGIN, y, line, 11, bold=True)
                y -= 15
            sim = "X" if q.answer is True else " "
            nao = "X" if q.answer is False else " "
            na = "X" if q.answer is None else " "
            pg.text(
                MARGIN + 10,
                y,
                f"Resposta:   [{sim}] Sim     [{nao}] Não     [{na}] N/A",
                10,
            )
            y -= 14
            if q.note:
                for line in _wrap(f"Obs.: {q.note}", 9.5, PAGE_W - 2 * MARGIN - 10):
                    pg.text(MARGIN + 10, y, line, 9.5)
                    y -= 13
            if q.photo:
                with Image.open(io.BytesIO(q.photo)) as im:
                    ratio = im.width / im.height
                h = photo_height
                w = min(h * ratio, PAGE_W - 2 * MARGIN - 10)
                h = w / ratio
                y -= h + 4
                pg.image(q.photo, MARGIN + 10, y, w, h)
            y -= 26
        if k == len(chunks) - 1 and footer:
            y = max(y, MARGIN + 20 + 14 * len(footer))
            for line in footer:
                pg.text(MARGIN, y, line, 9.5)
                y -= 14
    return _write(pages)


def _write(pages: list[_Page]) -> bytes:
    """Monta os objetos do PDF (catálogo, páginas, fontes, conteúdo e imagens) com a tabela xref."""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    def stream(dict_body: bytes, data: bytes) -> bytes:
        return b"<< %s /Length %d >>\nstream\n%s\nendstream" % (
            dict_body,
            len(data),
            data,
        )

    catalog = add(b"")  # preenchidos no fim (dependem do número dos outros objetos)
    pages_id = add(b"")
    f1 = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    f2 = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    )
    kids = []
    for pg in pages:
        xobjs = []
        for name, jpeg, w, h in pg.images:
            img = add(
                stream(
                    b"/Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
                    b"/BitsPerComponent 8 /Filter /DCTDecode" % (w, h),
                    jpeg,
                )
            )
            xobjs.append(b"/%s %d 0 R" % (name.encode(), img))
        content = add(stream(b"", b"\n".join(pg.ops)))
        kids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> /XObject << %s >> >> >>"
                % (pages_id, PAGE_W, PAGE_H, content, f1, f2, b" ".join(xobjs))
            )
        )
    objs[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
    objs[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n%s\nendobj\n" % (i, body))
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objs) + 1, catalog, xref)
    )
    return out.getvalue()
