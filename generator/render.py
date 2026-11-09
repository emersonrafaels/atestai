"""Motor mínimo de renderização procedural (PIL + numpy) para gerar fotos sintéticas.

Não é fotorrealista: o objetivo é ter cenas reconhecíveis (ambiente, equipamento,
antes/depois) para exercitar o pipeline do Atest.AI antes de ter a amostra histórica real.
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 960
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_M = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_C = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"


_WINDOWS_FONTS = {"r": "arial.ttf", "b": "arialbd.ttf", "m": "consola.ttf", "c": "ARIALN.TTF"}


def font(size, kind="r"):
    """DejaVu (Linux); no Windows, Arial/Consolas equivalentes; em último caso, a fonte embutida do Pillow."""
    for path in ({"r": FONT, "b": FONT_B, "m": FONT_M, "c": FONT_C}[kind], f"C:/Windows/Fonts/{_WINDOWS_FONTS[kind]}"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def clamp(c):
    return tuple(int(max(0, min(255, v))) for v in c)


def mul(c, k):
    return clamp([v * k for v in c])


def mix(a, b, t):
    return clamp([a[i] * (1 - t) + b[i] * t for i in range(3)])


# --------------------------------------------------------------------------- câmera
class Cam:
    def __init__(self, pos=(0.0, 0.0, 0.0), yaw=0.0, pitch=0.0, roll=0.0, f=760, w=W, h=H):
        self.pos = np.array(pos, float)
        self.yaw, self.pitch, self.roll = math.radians(yaw), math.radians(pitch), math.radians(roll)
        self.f, self.w, self.h = f, w, h

    def to_cam(self, p):
        x, y, z = np.array(p, float) - self.pos
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        x, z = x * cy - z * sy, x * sy + z * cy
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        y, z = y * cp - z * sp, y * sp + z * cp
        cr, sr = math.cos(self.roll), math.sin(self.roll)
        x, y = x * cr - y * sr, x * sr + y * cr
        return np.array([x, y, z])

    def proj_cam(self, q):
        return (self.w / 2 + self.f * q[0] / q[2], self.h / 2 - self.f * q[1] / q[2])

    def project_poly(self, pts, near=0.05):
        cam = [self.to_cam(p) for p in pts]
        out = []
        n = len(cam)
        for i in range(n):  # Sutherland–Hodgman contra o plano z = near
            a, b = cam[i], cam[(i + 1) % n]
            ina, inb = a[2] >= near, b[2] >= near
            if ina:
                out.append(a)
            if ina != inb:
                t = (near - a[2]) / (b[2] - a[2])
                out.append(a + t * (b - a))
        return [self.proj_cam(q) for q in out]

    def project(self, p):
        q = self.to_cam(p)
        if q[2] <= 0.05:
            return None
        return self.proj_cam(q)


# --------------------------------------------------------------------------- canvas
class Canvas:
    def __init__(self, cam: Cam | None = None, bg=(128, 128, 128), seed=0, w=W, h=H):
        self.w, self.h = w, h
        self.cam = cam or Cam(w=w, h=h)
        self.img = Image.new("RGB", (w, h), bg)
        self.rng = np.random.default_rng(seed)
        fine = self.rng.normal(0, 1, (h, w))
        coarse = np.array(
            Image.fromarray(((self.rng.normal(0, 1, (h // 16, w // 16)) + 4) * 30).clip(0, 255).astype("uint8")).resize((w, h), Image.BICUBIC), float
        )
        coarse = (coarse - coarse.mean()) / (coarse.std() + 1e-6)
        self.noise = 0.6 * fine + 0.8 * coarse
        self.draw = ImageDraw.Draw(self.img)

    # -- polígono 2D com textura e gradiente
    def poly2(self, p2, fill, tex=5.0, grad=None, soft=0, alpha=255):
        if len(p2) < 3:
            return
        xs = [p[0] for p in p2]
        ys = [p[1] for p in p2]
        x0, y0 = max(0, int(min(xs)) - 2 - soft * 2), max(0, int(min(ys)) - 2 - soft * 2)
        x1, y1 = min(self.w, int(max(xs)) + 3 + soft * 2), min(self.h, int(max(ys)) + 3 + soft * 2)
        if x1 <= x0 or y1 <= y0:
            return
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in p2], fill=alpha)
        if soft:
            mask = mask.filter(ImageFilter.GaussianBlur(soft))
        layer = np.empty((y1 - y0, x1 - x0, 3), float)
        layer[:] = fill
        layer += self.noise[y0:y1, x0:x1, None] * tex
        if grad:  # (gx, gy, amp): brilho varia linearmente na direção (gx, gy) em pixels de imagem
            gx, gy, amp = grad
            yy, xx = np.mgrid[y0:y1, x0:x1]
            t = ((xx - self.w / 2) * gx + (yy - self.h / 2) * gy) / max(self.w, self.h)
            layer *= (1 + amp * t)[..., None]
        part = Image.fromarray(layer.clip(0, 255).astype("uint8"))
        self.img.paste(part, (x0, y0), mask)

    def poly3(self, pts, fill, tex=5.0, grad=None, soft=0, alpha=255):
        self.poly2(self.cam.project_poly(pts), fill, tex, grad, soft, alpha)

    def line3(self, a, b, fill, width=2):
        pts = self.cam.project_poly([a, b, b])
        if len(pts) >= 2:
            self.draw.line([pts[0], pts[1]], fill=fill, width=width)

    # -- plano: O + u*U + v*V
    def on_plane(self, plane, uvs):
        origin, U, V = (np.array(x, float) for x in plane)
        return [origin + u * U + v * V for u, v in uvs]

    def rect_on(self, plane, u0, v0, u1, v1, fill, tex=4.0, grad=None, soft=0, alpha=255):
        self.poly3(self.on_plane(plane, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]), fill, tex, grad, soft, alpha)

    def blob_on(self, plane, cu, cv, r, fill, n=28, jitter=0.35, soft=6, alpha=200, tex=8, stretch=(1, 1)):
        rnd = random.Random(int(cu * 1000 + cv * 77 + r * 13))
        uvs = []
        for i in range(n):
            a = 2 * math.pi * i / n
            rr = r * (1 + rnd.uniform(-jitter, jitter))
            uvs.append((cu + stretch[0] * rr * math.cos(a), cv + stretch[1] * rr * math.sin(a)))
        self.poly3(self.on_plane(plane, uvs), fill, tex=tex, soft=soft, alpha=alpha)

    # -- caixa 3D (faces visíveis)
    def box(self, x0, x1, y0, y1, z0, z1, color, tex=4.0, light=(1.08, 0.92, 0.78, 0.7)):
        top, front, side, bottom = light
        c = self.cam.pos
        faces = []
        if c[1] > y1:
            faces.append(([(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)], top))
        if c[1] < y0:
            faces.append(([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], bottom))
        if c[2] < z0:
            faces.append(([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)], front))
        if c[2] > z1:
            faces.append(([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], front))
        if c[0] < x0:
            faces.append(([(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], side))
        if c[0] > x1:
            faces.append(([(x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)], side))
        for pts, k in faces:
            self.poly3(pts, mul(color, k), tex)

    # -- 2D helpers
    def rect(self, x0, y0, x1, y1, fill, tex=4.0, grad=None, soft=0, alpha=255):
        self.poly2([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill, tex, grad, soft, alpha)

    def rrect(self, box, r, fill, outline=None, width=1):
        self.draw.rounded_rectangle(box, r, fill=fill, outline=outline, width=width)

    def ellipse(self, box, fill=None, outline=None, width=1):
        self.draw.ellipse(box, fill=fill, outline=outline, width=width)

    def text(self, xy, s, size=24, fill=(20, 20, 20), kind="r", anchor="la"):
        self.draw.text(xy, s, font=font(size, kind), fill=fill, anchor=anchor)

    def glow(self, radius=18, threshold=235, amount=0.55):
        a = np.asarray(self.img, float)
        bright = (a.mean(axis=2) > threshold).astype("uint8") * 255
        g = Image.fromarray(bright).filter(ImageFilter.GaussianBlur(radius))
        ga = np.asarray(g, float)[..., None] / 255.0
        a = a + ga * amount * 255
        self.img = Image.fromarray(a.clip(0, 255).astype("uint8"))
        self.draw = ImageDraw.Draw(self.img)

    def refresh(self):
        self.draw = ImageDraw.Draw(self.img)


# --------------------------------------------------------------------------- pós-processamento "de celular"
def finish(img: Image.Image, seed=0, exposure=1.0, warm=0.0, vignette=0.35, blur=0.6, noise=3.5, desat=0.0, gamma=1.0):
    rng = np.random.default_rng(seed)
    a = np.asarray(img, float) / 255.0
    a = a**gamma
    a *= exposure
    if warm:
        a[..., 0] *= 1 + warm
        a[..., 2] *= 1 - warm
    if desat:
        g = a.mean(axis=2, keepdims=True)
        a = a * (1 - desat) + g * desat
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    a *= (1 - vignette * (r / 1.42) ** 2)[..., None]
    a = (a * 255 + rng.normal(0, noise, a.shape)).clip(0, 255).astype("uint8")
    out = Image.fromarray(a)
    if blur:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    return out


def illegible(img: Image.Image, seed=0):
    """Foto escura, tremida e sem foco: deve ser sinalizada como ilegível."""
    out = img.filter(ImageFilter.GaussianBlur(14))
    # tremido: média de deslocamentos
    a = np.zeros((img.height, img.width, 3), float)
    base = np.asarray(out, float)
    for dx in range(0, 60, 6):
        a += np.roll(base, dx, axis=1)
    a /= 10
    a *= 0.13
    rng = np.random.default_rng(seed)
    a += rng.normal(0, 9, a.shape)
    return Image.fromarray(a.clip(0, 255).astype("uint8"))
