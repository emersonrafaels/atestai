"""Simulação de câmera de celular: aproxima as cenas renderizadas de uma foto real tirada em campo.

O que denuncia uma imagem sintética, e o que cada etapa corrige:
- superfícies de cor chapada       → textura de superfície em várias escalas e sujeira de baixa frequência
- objetos "colados" no fundo        → sombra de contato (oclusão aproximada a partir das bordas)
- luz perfeitamente uniforme        → queda de luz a partir de uma fonte, brilho estourado (bloom) nas lâmpadas
- geometria e foco perfeitos        → leve perspectiva, aberração cromática, desfoque nas bordas, tremido ocasional
- cor neutra de computador          → balanço de branco de lâmpada fluorescente ou incandescente, curva de tom de celular
- pixels limpos                     → ruído de sensor (luminância e cor), redução de ruído e nitidez exagerada do celular

Tudo é determinístico pela semente: a mesma cena com a mesma semente gera a mesma foto (os casos de foto reaproveitada
dependem disso).
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

LIGHT = {
    "fluorescent": (0.97, 1.02, 1.03),
    "led": (1.0, 1.0, 1.02),
    "incandescent": (1.07, 1.0, 0.88),
    "day": (1.0, 1.0, 1.0),
    "shadow": (0.95, 0.99, 1.07),
}


def _value_noise(rng: np.random.Generator, h: int, w: int, scale: int) -> np.ndarray:
    """Ruído suave: grade aleatória pequena ampliada com interpolação bicúbica (−1 a 1)."""
    gh, gw = max(2, h // scale), max(2, w // scale)
    grade = Image.fromarray(((rng.random((gh, gw)) * 255).astype("uint8")), "L")
    return np.asarray(grade.resize((w, h), Image.BICUBIC), float) / 127.5 - 1


def _blur(a: np.ndarray, radius: float) -> np.ndarray:
    img = Image.fromarray(a.clip(0, 255).astype("uint8"))
    return np.asarray(img.filter(ImageFilter.GaussianBlur(radius)), float)


def _perspective(img: Image.Image, rng: np.random.Generator, strength: float) -> Image.Image:
    """Inclinação leve de quem fotografa de pé, com o celular um pouco fora do eixo."""
    w, h = img.size
    d = lambda: rng.uniform(-1, 1) * strength * w  # noqa: E731
    origin = [(0, 0), (w, 0), (w, h), (0, h)]
    target = [(d(), d()), (w + d(), d()), (w + d(), h + d()), (d(), h + d())]
    # coeficientes da transformação projetiva destino → origem
    A, b = [], []
    for (x, y), (u, v) in zip(target, origin, strict=True):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        b += [u, v]
    coef = np.linalg.solve(np.array(A, float), np.array(b, float))
    out = img.transform((w, h), Image.PERSPECTIVE, tuple(coef), Image.BICUBIC, fillcolor=(30, 30, 30))
    m = int(strength * w * 1.6) + 2  # corta a borda preta da transformação
    return out.crop((m, m, w - m, h - m)).resize((w, h), Image.BICUBIC)


def photograph(img: Image.Image, seed: int = 0, *, light: str | None = None, paper: bool = False, screen: bool = False) -> Image.Image:
    """Transforma um render em "foto de celular". `papel`: documento sobre a mesa; `tela`: foto do monitor do CFTV."""
    rng = np.random.default_rng(seed + 9001)
    img = img.convert("RGB")
    if not screen:
        img = _perspective(img, rng, rng.uniform(0.006, 0.02))
    a = np.asarray(img, float)
    h, w = a.shape[:2]
    lum = a.mean(axis=2)

    # 1) textura de superfície (3 escalas) e sujeira de baixa frequência, mais forte nas áreas lisas
    edges = np.asarray(Image.fromarray(lum.astype("uint8")).filter(ImageFilter.FIND_EDGES), float) / 255
    smooth = 1 - np.clip(_blur(np.repeat(edges[..., None] * 255, 3, 2), 3)[..., 0] / 60, 0, 1)
    texture = 0.55 * _value_noise(rng, h, w, 3) + 0.3 * _value_noise(rng, h, w, 14) + 0.15 * _value_noise(rng, h, w, 60)
    dirt = _value_noise(rng, h, w, 180)
    k_tex = 0.022 if screen else 0.05
    a *= (1 + k_tex * texture * (0.4 + 0.6 * smooth) - 0.035 * np.clip(dirt, 0, 1))[..., None]

    # 2) sombra de contato: escurece em volta das bordas fortes (objetos apoiados, cantos, molduras)
    if not screen:
        occlusion = _blur(np.repeat(edges[..., None] * 255, 3, 2), 9)[..., 0] / 255
        a *= (1 - np.clip(occlusion * 0.9, 0, 0.16))[..., None]

    # 3) iluminação: fonte de luz fora do centro, queda suave; brilho estourado nas áreas muito claras
    lx, ly = rng.uniform(0.15, 0.85) * w, rng.uniform(-0.2, 0.5) * h
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt(((xx - lx) / w) ** 2 + ((yy - ly) / h) ** 2)
    a *= (1.08 - rng.uniform(0.18, 0.32) * dist**1.3)[..., None]
    bright = np.clip((a.mean(axis=2) - 215) / 40, 0, 1)
    if bright.any():
        glow = _blur(np.repeat(bright[..., None] * 255, 3, 2), 18) / 255
        a += glow * rng.uniform(25, 45)

    # 4) balanço de branco e curva de tom de celular (contraste em S, realces que não estouram de vez)
    color = LIGHT[light or rng.choice(list(LIGHT)[:4], p=[0.45, 0.3, 0.15, 0.1])]
    a *= np.array(color) * rng.uniform(0.97, 1.04, 3)
    x = np.clip(a / 255, 0, 1.3)
    x = np.where(x < 1, x, 1 - (1 - x) * 0.3)  # compressão dos realces
    x = np.clip(x, 0, 1)
    x = x + rng.uniform(0.25, 0.45) * x * (1 - x) * (2 * x - 1)  # curva em S
    g = x.mean(axis=2, keepdims=True)
    x = g + (x - g) * rng.uniform(0.86, 1.02)  # celular satura pouco em luz artificial
    a = np.clip(x, 0, 1) * 255

    # 5) lente: aberração cromática radial, vinheta e desfoque nas bordas
    out = Image.fromarray(a.astype("uint8"))
    r, gch, b = out.split()
    s = rng.uniform(0.0015, 0.004)
    r = r.resize((int(w * (1 + s)), int(h * (1 + s))), Image.BICUBIC).crop((int(w * s / 2), int(h * s / 2), int(w * s / 2) + w, int(h * s / 2) + h))
    out = Image.merge("RGB", (r, gch, b))
    a = np.asarray(out, float)
    radius = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 1.42
    a *= (1 - rng.uniform(0.18, 0.32) * radius**2.2)[..., None]
    blurred = _blur(a, rng.uniform(1.2, 2.4))
    t = np.clip((radius - 0.55) / 0.45, 0, 1)[..., None] * (0.5 if paper else 0.8)
    a = a * (1 - t) + blurred * t

    # 6) tremido ocasional de mão
    if rng.random() < 0.25 and not paper:
        shift = int(rng.uniform(2, 5))
        a = sum(np.roll(a, k, axis=1 if rng.random() < 0.7 else 0) for k in range(shift)) / shift

    # 7) sensor: ruído de disparo (mais nas sombras), ruído de cor em manchas; depois o celular "limpa" e aplica nitidez
    level = np.clip(a.mean(axis=2, keepdims=True) / 255, 0.05, 1)
    a += rng.normal(0, 1, a.shape) * (5.5 * np.sqrt(1 - level) + 1.5)
    chroma = np.stack([_value_noise(rng, h, w, 4) for _ in range(3)], axis=2)
    a += chroma * 3.0
    out = Image.fromarray(a.clip(0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.7))
    out = out.filter(ImageFilter.UnsharpMask(radius=2.2, percent=int(rng.uniform(70, 110)), threshold=2))
    if screen:  # moiré leve da foto de monitor
        a = np.asarray(out, float)
        a *= (1 + 0.035 * np.sin(xx * rng.uniform(0.9, 1.3) + yy * rng.uniform(0.3, 0.7)))[..., None]
        out = Image.fromarray(a.clip(0, 255).astype("uint8"))
    return out
