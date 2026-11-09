"""Cenas sintéticas usadas como fotos de chamados SETA (predial) e SISR (segurança).

Cada função devolve uma PIL.Image 1280x960 (antes do pós-processamento "de celular").
"""

from __future__ import annotations

import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from render import Cam, Canvas, H, W, font, mix, mul

# ============================================================================ ambientes 3D
FLOOR_Y = -1.55
CEIL_Y = 1.25


def room(
    cv: Canvas,
    w=6.0,
    d=7.0,
    wall=(226, 218, 200),
    ceil=(238, 238, 234),
    floor=(160, 150, 138),
    tile=0.6,
    tile_line=None,
    side_k=(0.9, 0.84),
    wall_tiles=None,
    hf=-FLOOR_Y,
    hc=CEIL_Y,
    wall_tex=2.0,
):
    near = -3.0
    L, R = -w / 2, w / 2
    # teto, piso, paredes
    cv.poly3([(L, hc, near), (R, hc, near), (R, hc, d), (L, hc, d)], ceil, tex=1.5, grad=(0, 1, 0.12))
    cv.poly3([(L, -hf, near), (R, -hf, near), (R, -hf, d), (L, -hf, d)], floor, tex=6, grad=(0, -1, 0.25))
    cv.poly3([(L, -hf, d), (R, -hf, d), (R, hc, d), (L, hc, d)], wall, tex=wall_tex, grad=(0, -1, 0.12))
    cv.poly3([(L, -hf, near), (L, -hf, d), (L, hc, d), (L, hc, near)], mul(wall, side_k[0]), tex=wall_tex, grad=(1, 0, 0.15))
    cv.poly3([(R, -hf, near), (R, -hf, d), (R, hc, d), (R, hc, near)], mul(wall, side_k[1]), tex=wall_tex, grad=(-1, 0, 0.15))
    # juntas do piso
    lc = tile_line or mul(floor, 0.82)
    if tile:
        x = L
        while x <= R + 1e-6:
            cv.line3((x, -hf, 0.2), (x, -hf, d), lc, 2)
            x += tile
        z = 0.0
        while z <= d + 1e-6:
            cv.line3((L, -hf, z), (R, -hf, z), lc, 2)
            z += tile
    planes = {
        "back": ((L, -hf, d - 0.001), (1, 0, 0), (0, 1, 0)),
        "left": ((L + 0.001, -hf, 0), (0, 0, 1), (0, 1, 0)),
        "right": ((R - 0.001, -hf, 0), (0, 0, 1), (0, 1, 0)),
        "ceil": ((L, hc - 0.001, 0), (1, 0, 0), (0, 0, 1)),
        "w": w,
        "d": d,
        "hf": hf,
        "hc": hc,
    }
    if wall_tiles:  # azulejos nas paredes
        step, col = wall_tiles
        hh = hf + hc
        for name, length in (("back", w), ("left", d), ("right", d)):
            origin, U, V = (np.array(x, float) for x in planes[name])
            u = 0.0
            while u <= length:
                cv.line3(origin + u * U, origin + u * U + hh * V, col, 2)
                u += step
            v = 0.0
            while v <= hh:
                cv.line3(origin + v * V, origin + length * U + v * V, col, 2)
                v += step
    return planes


def ceiling_lights(cv: Canvas, planes, kind="fluor", rows=((-1.4,), (1.4,)), zs=(1.8, 3.8, 5.8), dead=(), dim=()):
    hc = planes["hc"] - 0.002
    idx = 0
    for xs in rows:
        for x in xs:
            for z in zs:
                if kind == "led":
                    s = 0.31
                    cv.poly3([(x - s, hc, z - s), (x + s, hc, z - s), (x + s, hc, z + s), (x - s, hc, z + s)], (205, 205, 205), tex=1)
                    s2 = 0.28
                    cv.poly3(
                        [(x - s2, hc - 0.001, z - s2), (x + s2, hc - 0.001, z - s2), (x + s2, hc - 0.001, z + s2), (x - s2, hc - 0.001, z + s2)],
                        (252, 252, 250),
                        tex=0.5,
                    )
                else:
                    sx, sz = 0.31, 0.62
                    cv.poly3([(x - sx, hc, z - sz), (x + sx, hc, z - sz), (x + sx, hc, z + sz), (x - sx, hc, z + sz)], (196, 196, 190), tex=1.5)
                    # aletas
                    for t in (-0.16, 0.16):
                        on = idx not in dead
                        c = (250, 250, 240) if on and idx not in dim else ((105, 105, 100) if not on else (196, 206, 178))
                        cv.poly3(
                            [
                                (x + t - 0.035, hc - 0.001, z - sz + 0.05),
                                (x + t + 0.035, hc - 0.001, z - sz + 0.05),
                                (x + t + 0.035, hc - 0.001, z + sz - 0.05),
                                (x + t - 0.035, hc - 0.001, z + sz - 0.05),
                            ],
                            c,
                            tex=0.5,
                        )
                    for k in range(-5, 6):
                        zz = z + k * 0.1
                        cv.line3((x - sx, hc - 0.002, zz), (x + sx, hc - 0.002, zz), (175, 175, 170), 1)
                idx += 1


def desk(cv: Canvas, x0, x1, z0, z1, top=(196, 172, 135), body=(90, 90, 96), monitor=True):
    y = FLOOR_Y
    cv.box(x0 + 0.05, x1 - 0.05, y, y + 0.72, z1 - 0.06, z1 - 0.02, body)  # painel frontal fundo
    cv.box(x0, x0 + 0.05, y, y + 0.72, z0, z1, body)
    cv.box(x1 - 0.05, x1, y, y + 0.72, z0, z1, body)
    cv.box(x0, x1, y + 0.72, y + 0.76, z0, z1, top)
    if monitor:
        mx = (x0 + x1) / 2
        cv.box(mx - 0.05, mx + 0.05, y + 0.76, y + 0.95, z1 - 0.25, z1 - 0.18, (40, 40, 44))
        cv.box(mx - 0.30, mx + 0.30, y + 0.95, y + 1.30, z1 - 0.24, z1 - 0.20, (28, 28, 32))
        cv.poly3(
            [
                (mx - 0.28, y + 0.97, z1 - 0.241),
                (mx + 0.28, y + 0.97, z1 - 0.241),
                (mx + 0.28, y + 1.28, z1 - 0.241),
                (mx - 0.28, y + 1.28, z1 - 0.241),
            ],
            (70, 95, 130),
            tex=3,
        )
        cv.box(mx - 0.22, mx + 0.22, y + 0.76, y + 0.78, z0 + 0.12, z0 + 0.28, (55, 55, 60))


def chair(cv: Canvas, x, z, color=(45, 45, 52)):
    y = FLOOR_Y
    cv.box(x - 0.03, x + 0.03, y, y + 0.42, z - 0.03, z + 0.03, (30, 30, 30))
    cv.box(x - 0.25, x + 0.25, y + 0.42, y + 0.50, z - 0.25, z + 0.25, color)
    cv.box(x - 0.23, x + 0.23, y + 0.55, y + 1.05, z - 0.30, z - 0.24, color)


def cabinet(cv: Canvas, x0, x1, z0, z1, h=1.2, color=(150, 150, 155)):
    cv.box(x0, x1, FLOOR_Y, FLOOR_Y + h, z0, z1, color)


def door_on(cv: Canvas, plane, u0, width=0.9, height=2.1, color=(150, 110, 70), frame=(235, 235, 230)):
    cv.rect_on(plane, u0 - 0.07, 0, u0 + width + 0.07, height + 0.07, frame, tex=2)
    cv.rect_on(plane, u0, 0, u0 + width, height, color, tex=7)
    cv.rect_on(plane, u0 + width - 0.14, 1.0, u0 + width - 0.06, 1.04, (200, 200, 205), tex=1)


def window_on(cv: Canvas, plane, u0, u1, v0, v1, blinds=True):
    cv.rect_on(plane, u0 - 0.05, v0 - 0.05, u1 + 0.05, v1 + 0.05, (225, 225, 225), tex=1)
    cv.rect_on(plane, u0, v0, u1, v1, (205, 225, 240), tex=2)
    if blinds:
        v = v1
        while v > v0 + 0.25:
            cv.rect_on(plane, u0, v - 0.035, u1, v, (236, 236, 232), tex=1)
            v -= 0.06


def board_on(cv: Canvas, plane, u0, u1, v0, v1):
    cv.rect_on(plane, u0 - 0.03, v0 - 0.03, u1 + 0.03, v1 + 0.03, (120, 90, 60), tex=2)
    cv.rect_on(plane, u0, v0, u1, v1, (190, 150, 105), tex=9)
    rnd = random.Random(int(u0 * 100))
    for _ in range(6):
        a = rnd.uniform(u0 + 0.05, u1 - 0.3)
        b = rnd.uniform(v0 + 0.05, v1 - 0.3)
        cv.rect_on(plane, a, b, a + 0.21, b + 0.28, (245, 245, 240), tex=1)


def split_on(cv: Canvas, plane, u0, v0, width=0.9):
    cv.rect_on(plane, u0, v0, u0 + width, v0 + 0.3, (240, 240, 238), tex=1.5)
    cv.rect_on(plane, u0 + 0.05, v0 + 0.02, u0 + width - 0.05, v0 + 0.06, (90, 90, 95), tex=1)


def paint_bucket(cv: Canvas, p, r=0.16, h=0.32, color=(235, 235, 240), label=(40, 110, 180)):
    a = cv.cam.project(p)
    b = cv.cam.project((p[0], p[1] + h, p[2]))
    e = cv.cam.project((p[0] + r, p[1], p[2]))
    if not (a and b and e):
        return
    rx = abs(e[0] - a[0])
    ry = rx * 0.35
    cv.draw.rectangle([a[0] - rx, b[1], a[0] + rx, a[1]], fill=color)
    cv.draw.ellipse([a[0] - rx, a[1] - ry, a[0] + rx, a[1] + ry], fill=mul(color, 0.85))
    cv.draw.rectangle([a[0] - rx, b[1] + (a[1] - b[1]) * 0.3, a[0] + rx, b[1] + (a[1] - b[1]) * 0.7], fill=label)
    cv.draw.ellipse([a[0] - rx, b[1] - ry, a[0] + rx, b[1] + ry], fill=(220, 220, 225), outline=(150, 150, 155), width=2)
    cv.draw.arc([a[0] - rx * 0.9, b[1] - ry * 4, a[0] + rx * 0.9, b[1] + ry], 180, 360, fill=(90, 90, 90), width=3)


def ladder(cv: Canvas, x, z, h=1.6, color=(185, 185, 190)):
    y = FLOOR_Y
    pts = [(x - 0.25, y, z), (x - 0.12, y + h, z + 0.25), (x + 0.12, y + h, z + 0.25), (x + 0.25, y, z)]
    back = [(x - 0.25, y, z + 0.6), (x + 0.25, y, z + 0.6)]
    cv.line3(back[0], pts[1], mul(color, 0.8), 6)
    cv.line3(back[1], pts[2], mul(color, 0.8), 6)
    cv.line3(pts[0], pts[1], color, 8)
    cv.line3(pts[3], pts[2], color, 8)
    for k in range(1, 5):
        t = k / 5
        a = (pts[0][0] + (pts[1][0] - pts[0][0]) * t, y + h * t, z + 0.25 * t)
        b = (pts[3][0] + (pts[2][0] - pts[3][0]) * t, y + h * t, z + 0.25 * t)
        cv.line3(a, b, color, 6)
    cv.line3((x - 0.12, y + h, z + 0.25), (x + 0.12, y + h, z + 0.3), (120, 120, 125), 10)


def water_stain(cv: Canvas, plane, cu, cv_, r, mold=True):
    cv.blob_on(plane, cu, cv_, r * 1.25, (196, 170, 120), soft=10, alpha=120, tex=10)
    cv.blob_on(plane, cu, cv_, r, (170, 140, 90), soft=6, alpha=150, tex=12)
    cv.blob_on(plane, cu + r * 0.15, cv_ - r * 0.1, r * 0.55, (140, 110, 70), soft=4, alpha=140, tex=14)
    if mold:
        rnd = random.Random(int(cu * 31 + cv_ * 17))
        for _ in range(40):
            a = rnd.uniform(0, 2 * math.pi)
            rr = rnd.uniform(0, r * 0.9)
            cv.blob_on(plane, cu + rr * math.cos(a), cv_ + rr * math.sin(a), rnd.uniform(0.01, 0.035), (60, 62, 50), n=10, soft=1, alpha=180, tex=6)


def peeling(cv: Canvas, plane, cu, cv_, r):
    rnd = random.Random(int(cu * 13 + cv_ * 7))
    for _ in range(9):
        a = rnd.uniform(0, 2 * math.pi)
        rr = rnd.uniform(0, r)
        cu2, cv2 = cu + rr * math.cos(a), cv_ + rr * math.sin(a)
        s = rnd.uniform(0.04, 0.12)
        cv.blob_on(plane, cu2, cv2, s * 1.15, (120, 110, 95), n=14, jitter=0.5, soft=1, alpha=200, tex=6)
        cv.blob_on(plane, cu2, cv2, s, (205, 200, 188), n=14, jitter=0.5, soft=0, alpha=255, tex=14)


def backoffice(seed=0, view="A", wall=None, lights="fluor", stains=False, painting_gear=False, dead=(), dim=(), clutter=True, layout=None):
    """Backoffice/escritório. `layout` fixa a geometria e o mobiliário (mesma sala em fotos de antes/depois)."""
    lay = random.Random(seed if layout is None else layout)
    wall = wall or lay.choice([(228, 220, 202), (222, 226, 214), (232, 226, 218), (214, 222, 230), (236, 230, 206)])
    w = lay.uniform(5.6, 7.2)
    d = lay.uniform(6.2, 8.0)
    jy = lay.uniform(-7, 7)
    if view == "A":
        cam = Cam(pos=(0.3, 0.05, 0.0), yaw=-6 + jy, pitch=-6, f=700)
    elif view == "B":
        cam = Cam(pos=(-1.2, 0.0, 0.5), yaw=22 + jy, pitch=-4, f=680)
    else:  # C: do canto oposto
        cam = Cam(pos=(w / 2 - 0.6, 0.15, 0.4), yaw=-34 + jy * 0.5, pitch=-8, f=640)
    cv = Canvas(cam, seed=seed)
    floor = lay.choice([(168, 158, 146), (150, 150, 150), (176, 166, 140), (120, 110, 100)])
    pl = room(cv, w=w, d=d, wall=wall, floor=floor, tile=lay.choice([0.6, 0.45, 0.0]))
    rows = ((-w / 4.5,), (w / 4.5,))
    zs = tuple(z for z in (1.8, 3.8, 5.8, 7.6) if z < d - 0.5)
    ceiling_lights(cv, pl, kind=lights, dead=dead, dim=dim, rows=rows, zs=zs)
    du = lay.uniform(0.4, w - 1.6)
    door_on(cv, pl["back"], du, color=lay.choice([(150, 110, 70), (120, 120, 125), (175, 140, 95)]))
    bu = (du + 1.3) if du < w / 2 else max(0.3, du - 1.8)
    board_on(cv, pl["back"], bu, bu + 1.2, 1.15, 1.95)
    split_on(cv, pl["back"], w - 1.6, 2.3)
    if lay.random() < 0.7:
        window_on(cv, pl["right"], 2.0, min(d - 0.6, 4.8), 0.95, 2.25)
    if stains:
        water_stain(cv, pl["back"], w - 1.0, 2.45, 0.45)
        water_stain(cv, pl["right"], d - 0.8, 2.3, 0.35)
        peeling(cv, pl["back"], w - 1.3, 1.75, 0.35)
    # mobiliário (fundo -> frente)
    if lay.random() < 0.6:
        cabinet(cv, -w / 2 + 0.05, -w / 2 + 0.5, d - 2.6, d - 0.6, h=1.25, color=lay.choice([(150, 150, 155), (120, 95, 70)]))
    top = lay.choice([(196, 172, 135), (230, 230, 228), (150, 120, 90)])
    zb = d - 2.4
    for x0 in sorted(lay.sample([-2.0, -0.4, 0.8, 1.9], k=lay.choice([2, 3])), reverse=True):
        if x0 + 1.5 < w / 2:
            desk(cv, x0, x0 + 1.4, zb, zb + 0.8, top=top)
            chair(cv, x0 + 0.7, zb - 0.35)
    if clutter:
        x0 = lay.choice([-2.0, 0.4])
        desk(cv, x0, x0 + 1.5, zb - 2.2, zb - 1.4, top=top)
        chair(cv, x0 + 0.8, zb - 2.55)
    if painting_gear:
        ladder(cv, 2.0, 2.6)
        paint_bucket(cv, (1.4, FLOOR_Y, 2.2))
        paint_bucket(cv, (1.75, FLOOR_Y, 2.5), label=(200, 80, 50))
    cv.glow(14, 247, 0.35)
    return cv.img


def ceiling_view(seed=0, lights="fluor", stains=False, wall=None, layout=None):
    lay = random.Random(seed if layout is None else layout)
    wall = wall or lay.choice([(228, 220, 202), (222, 226, 214), (232, 226, 218), (214, 222, 230)])
    cam = Cam(pos=(lay.uniform(-0.6, 0.6), -0.2, 0.6), yaw=lay.uniform(-15, 15), pitch=lay.uniform(32, 44), f=640)
    cv = Canvas(cam, seed=seed)
    w = lay.uniform(5.6, 7.2)
    pl = room(cv, w=w, d=7.2, wall=wall, floor=(168, 158, 146), ceil=(236, 236, 232))
    zs = (2.0, 4.2, 6.2) if lay.random() < 0.5 else (1.6, 3.4, 5.2, 7.0)
    ceiling_lights(cv, pl, kind=lights, zs=zs, rows=((-w / 4.5,), (w / 4.5,)) if lay.random() < 0.6 else ((0.0,),))
    split_on(cv, pl["back"], 4.6, 2.3)
    if stains:
        cplane = pl["ceil"]
        water_stain(cv, cplane, 3.6, 3.1, 0.55)
        water_stain(cv, cplane, 4.3, 3.7, 0.3)
        # bolha/estufamento
        cv.blob_on(cplane, 3.5, 3.0, 0.18, (205, 190, 160), soft=8, alpha=160)
    cv.glow(16, 247, 0.35)
    return cv.img


def bathroom(seed=0):
    cam = Cam(pos=(0.0, 0.1, 0.2), yaw=12, pitch=-8, f=640)
    cv = Canvas(cam, seed=seed)
    pl = room(cv, w=3.4, d=4.2, wall=(236, 238, 238), floor=(120, 125, 130), tile=0.3, wall_tiles=(0.3, (200, 205, 208)))
    ceiling_lights(cv, pl, kind="led", rows=((0.0,),), zs=(2.2,))
    # bancada com cubas e espelho
    cv.box(-1.7, 0.4, FLOOR_Y + 0.8, FLOOR_Y + 0.88, 3.65, 4.2, (40, 40, 42))
    cv.box(-1.65, 0.35, FLOOR_Y, FLOOR_Y + 0.8, 4.0, 4.2, (70, 70, 74))
    for x in (-1.2, -0.3):
        p = cam.project((x, FLOOR_Y + 0.885, 3.95))
        if p:
            cv.ellipse([p[0] - 55, p[1] - 14, p[0] + 55, p[1] + 14], fill=(245, 245, 245), outline=(180, 180, 180), width=2)
    cv.rect_on(pl["back"], 0.1, 1.15, 2.0, 2.3, (175, 195, 205), tex=3)
    # divisórias de box sanitário
    cv.box(0.55, 1.7, FLOOR_Y + 0.15, FLOOR_Y + 2.0, 1.2, 1.24, (95, 120, 150))
    cv.box(0.55, 0.59, FLOOR_Y + 0.15, FLOOR_Y + 2.0, 1.24, 4.1, (95, 120, 150))
    cv.box(0.59, 1.7, FLOOR_Y + 0.15, FLOOR_Y + 2.0, 2.6, 2.64, (95, 120, 150))
    cv.glow(14, 247, 0.3)
    return cv.img


def storage(seed=0):
    cam = Cam(pos=(0.0, 0.1, 0.0), yaw=-4, pitch=-5, f=650)
    cv = Canvas(cam, seed=seed)
    pl = room(cv, w=5.0, d=9.0, wall=(178, 178, 172), floor=(128, 128, 124), tile=0, ceil=(190, 190, 186))
    ceiling_lights(cv, pl, kind="fluor", rows=((0.0,),), zs=(2.5, 5.0, 7.5))
    rnd = random.Random(seed)
    for side in (-1, 1):
        x0 = -2.45 if side < 0 else 1.55
        x1 = x0 + 0.9
        for z0 in (2.0, 4.5, 7.0):
            for xx in (x0, x1 - 0.05):
                cv.box(xx, xx + 0.05, FLOOR_Y, FLOOR_Y + 2.2, z0, z0 + 0.05, (60, 90, 150))
                cv.box(xx, xx + 0.05, FLOOR_Y, FLOOR_Y + 2.2, z0 + 2.0, z0 + 2.05, (60, 90, 150))
            for lvl in (0.1, 0.8, 1.5, 2.15):
                cv.box(x0, x1, FLOOR_Y + lvl, FLOOR_Y + lvl + 0.05, z0, z0 + 2.05, (200, 120, 50))
                zz = z0 + 0.1
                while zz < z0 + 1.8 and lvl < 2.1:
                    bh = rnd.uniform(0.25, 0.55)
                    bw = rnd.uniform(0.3, 0.55)
                    cv.box(
                        x0 + 0.05,
                        x1 - 0.1,
                        FLOOR_Y + lvl + 0.05,
                        FLOOR_Y + lvl + 0.05 + bh,
                        zz,
                        zz + bw,
                        mix((180, 140, 95), (200, 165, 120), rnd.random()),
                    )
                    zz += bw + 0.05
    cv.glow(14, 247, 0.3)
    return cv.img


# ============================================================================ fachada (2D)
def facade(seed=0, color=(214, 208, 196)):
    cv = Canvas(seed=seed)
    # céu
    for y in range(0, 300):
        t = y / 300
        cv.draw.line([(0, y), (W, y)], fill=mix((120, 170, 225), (200, 222, 240), t))
    cv.rect(0, 70, W, 800, color, tex=6, grad=(0, -1, 0.1))
    cv.rect(0, 70, W, 90, mul(color, 0.8), tex=3)
    # janelas do 1º andar
    for x in range(90, W - 100, 230):
        cv.rect(x, 140, x + 150, 300, (225, 225, 225), tex=1)
        cv.rect(x + 8, 148, x + 142, 292, (95, 120, 145), tex=4, grad=(1, 1, 0.3))
        cv.draw.line([(x + 75, 148), (x + 75, 292)], fill=(225, 225, 225), width=5)
    # faixa de identificação (genérica)
    cv.rect(0, 360, W, 450, (35, 60, 110), tex=2)
    cv.text((W / 2, 405), "AGÊNCIA 0418", 54, (245, 245, 245), "b", anchor="mm")
    # vitrine e portas de vidro
    cv.rect(60, 470, W - 60, 800, (190, 190, 195), tex=1)
    for x in range(70, W - 70, 190):
        cv.rect(x, 480, x + 180, 800, (60, 75, 90), tex=3, grad=(1, -1, 0.5))
        cv.poly2([(x + 20, 490), (x + 70, 490), (x + 10, 640), (x + 5, 640)], (140, 160, 175), tex=1, alpha=90)
    cv.rect(W / 2 - 180, 480, W / 2 + 180, 800, (190, 190, 195), tex=1)
    cv.rect(W / 2 - 170, 490, W / 2 - 4, 800, (75, 92, 108), tex=3, grad=(1, -1, 0.4))
    cv.rect(W / 2 + 4, 490, W / 2 + 170, 800, (75, 92, 108), tex=3, grad=(1, -1, 0.4))
    cv.rect(W / 2 - 22, 620, W / 2 - 12, 700, (210, 210, 210), tex=1)
    cv.rect(W / 2 + 12, 620, W / 2 + 22, 700, (210, 210, 210), tex=1)
    # calçada
    cv.rect(0, 800, W, H, (150, 148, 142), tex=10)
    for x in range(-200, W + 200, 160):
        cv.draw.line([(x, 800), (x - 120, H)], fill=(125, 123, 118), width=3)
    cv.draw.line([(0, 880), (W, 880)], fill=(125, 123, 118), width=3)
    # vaso
    cv.rect(1120, 700, 1220, 800, (110, 80, 60), tex=6)
    cv.ellipse([1095, 600, 1245, 720], fill=(60, 110, 55))
    return cv.img


# ============================================================================ CFTV
def atm_room(cv: Canvas):
    pl = room(cv, w=7.0, d=7.5, wall=(225, 225, 222), floor=(175, 172, 165), tile=0.6)
    ceiling_lights(cv, pl, kind="led", rows=((-1.8, 1.8),), zs=(2.0, 4.5))
    # vidro da fachada na lateral direita
    cv.rect_on(pl["right"], 0.5, 0.0, 6.5, 2.6, (230, 238, 242), tex=2)
    for u in (0.5, 2.0, 3.5, 5.0, 6.5):
        cv.rect_on(pl["right"], u - 0.03, 0, u + 0.03, 2.6, (140, 140, 145), tex=1)
    for x in (-2.6, -1.4, -0.2, 1.0):
        z1 = 7.48
        z0 = z1 - 0.75
        cv.box(x, x + 0.85, FLOOR_Y, FLOOR_Y + 1.65, z0, z1, (70, 74, 82))
        cv.box(x + 0.02, x + 0.83, FLOOR_Y + 1.0, FLOOR_Y + 1.45, z0 - 0.12, z0, (55, 58, 64))
        cv.poly3(
            [
                (x + 0.15, FLOOR_Y + 1.08, z0 - 0.121),
                (x + 0.70, FLOOR_Y + 1.08, z0 - 0.121),
                (x + 0.70, FLOOR_Y + 1.40, z0 - 0.121),
                (x + 0.15, FLOOR_Y + 1.40, z0 - 0.121),
            ],
            (90, 150, 190),
            tex=2,
        )
        cv.box(x + 0.2, x + 0.65, FLOOR_Y + 0.85, FLOOR_Y + 0.95, z0 - 0.15, z0, (150, 150, 155))
    # pessoa usando terminal (silhueta simples)
    cv.box(-1.15, -0.85, FLOOR_Y, FLOOR_Y + 0.85, 6.1, 6.35, (40, 45, 70))
    cv.box(-1.2, -0.8, FLOOR_Y + 0.85, FLOOR_Y + 1.5, 6.05, 6.35, (150, 60, 50))
    p = cv.cam.project((-1.0, FLOOR_Y + 1.65, 6.2))
    if p:
        cv.ellipse([p[0] - 22, p[1] - 26, p[0] + 22, p[1] + 26], fill=(110, 80, 60))
    return pl


def corridor_room(cv: Canvas):
    pl = room(cv, w=2.6, d=12.0, wall=(222, 215, 200), floor=(150, 140, 128), tile=0.5)
    ceiling_lights(cv, pl, kind="fluor", rows=((0.0,),), zs=(2.0, 5.0, 8.0, 11.0))
    for u in (2.5, 6.5, 9.5):
        door_on(cv, pl["left"], u, color=(120, 95, 70))
    for u in (4.0, 8.0):
        door_on(cv, pl["right"], u, color=(120, 95, 70))
    cv.box(-0.4, 0.4, FLOOR_Y, FLOOR_Y + 1.9, 11.4, 11.9, (180, 60, 50))
    return pl


def parking_room(cv: Canvas):
    pl = room(cv, w=12.0, d=16.0, wall=(150, 150, 148), floor=(95, 95, 98), tile=0, ceil=(120, 120, 118), hc=1.6)
    for x in (-4.5, -1.5, 1.5, 4.5):
        cv.line3((x, FLOOR_Y, 6), (x, FLOOR_Y, 15), (230, 220, 120), 4)
    rnd = random.Random(3)
    for x in (-3.0, 0.0, 3.0):
        col = rnd.choice([(150, 30, 30), (200, 200, 205), (30, 50, 90), (40, 40, 40)])
        cv.box(x - 0.9, x + 0.9, FLOOR_Y + 0.2, FLOOR_Y + 1.0, 10, 14.3, col)
        cv.box(x - 0.8, x + 0.8, FLOOR_Y + 1.0, FLOOR_Y + 1.45, 11, 13.2, mul(col, 0.8))
    ceiling_lights(cv, pl, kind="fluor", rows=((-3.0, 3.0),), zs=(5.0, 10.0))
    return pl


CCTV_BACKGROUND = None  # gancho: (scene, seed, (w, h), tile) → Image | None; o gerador aponta para as fotos reais


def cctv_frame(scene="atm", seed=0, label="CAM 04", stamp="30/09/2026 14:22:10", blur=0.0, w=W, h=H, tint=(0.95, 1.0, 1.05), tile=False):
    """Imagem de câmera de CFTV. Se houver foto de fundo (gancho CCTV_BACKGROUND), ela substitui a cena 3D; o tratamento de
    câmera (cor lavada, ruído, desfoque) e o texto (câmera, data/hora) são aplicados por cima nos dois casos."""
    bg = CCTV_BACKGROUND(scene, seed, (w, h), tile) if CCTV_BACKGROUND is not None and scene in ("atm", "corridor", "parking", "office") else None
    if bg is not None:
        cv = Canvas(seed=seed, w=w, h=h)
        cv.img = bg.convert("RGB").resize((w, h))
        cv.refresh()
    elif scene == "atm":
        cam = Cam(pos=(-3.1, 1.05, 0.4), yaw=28, pitch=-30, f=560 * w / W, w=w, h=h)
        cv = Canvas(cam, seed=seed, w=w, h=h)
        atm_room(cv)
    elif scene == "corridor":
        cam = Cam(pos=(0.9, 1.0, 0.3), yaw=-6, pitch=-18, f=520 * w / W, w=w, h=h)
        cv = Canvas(cam, seed=seed, w=w, h=h)
        corridor_room(cv)
    elif scene == "parking":
        cam = Cam(pos=(-5.5, 1.4, 0.5), yaw=22, pitch=-20, f=520 * w / W, w=w, h=h)
        cv = Canvas(cam, seed=seed, w=w, h=h)
        parking_room(cv)
    elif scene == "office":
        img = backoffice(seed=seed, view="A").resize((w, h))
        cv = Canvas(seed=seed, w=w, h=h)
        cv.img = img
        cv.refresh()
    else:
        raise ValueError(scene)
    cv.glow(10, 247, 0.25)
    img = cv.img
    a = np.asarray(img, float)
    g = a.mean(axis=2, keepdims=True)
    a = a * 0.35 + g * 0.65
    a *= np.array(tint)
    a = a + np.random.default_rng(seed).normal(0, 6, a.shape)
    img = Image.fromarray(a.clip(0, 255).astype("uint8"))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    d = ImageDraw.Draw(img)
    fs = max(12, int(30 * w / W))
    d.text((int(22 * w / W), int(18 * h / H)), label, font=font(fs, "m"), fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
    if stamp:
        d.text(
            (w - int(22 * w / W), h - int(18 * h / H)),
            stamp,
            font=font(fs, "m"),
            fill=(255, 255, 255),
            anchor="rd",
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )
    return img


def dome_camera(seed=0):
    cam = Cam(pos=(0, 0, 0), yaw=5, pitch=62, f=700)
    cv = Canvas(cam, seed=seed)
    y = 1.0
    cv.poly3([(-6, y, -2), (6, y, -2), (6, y, 8), (-6, y, 8)], (226, 226, 222), tex=3, grad=(0, 1, 0.2))
    x = -3.0
    while x < 3:
        cv.line3((x, y - 0.001, -0.5), (x, y - 0.001, 6), (170, 170, 168), 3)
        x += 0.625
    z = 0.0
    while z < 6:
        cv.line3((-3, y - 0.001, z), (3, y - 0.001, z), (170, 170, 168), 3)
        z += 0.625
    p = cam.project((0.12, y, 0.75))
    r = 120
    cv.ellipse([p[0] - r, p[1] - r * 0.8, p[0] + r, p[1] + r * 0.8], fill=(245, 245, 245), outline=(200, 200, 200), width=3)
    r2 = 88
    cv.ellipse([p[0] - r2, p[1] - r2 * 0.8, p[0] + r2, p[1] + r2 * 0.8], fill=(35, 38, 45))
    cv.ellipse([p[0] - r2 * 0.6, p[1] - r2 * 0.6, p[0] - r2 * 0.1, p[1] - r2 * 0.25], fill=(110, 115, 130))
    cv.ellipse([p[0] - 18, p[1] - 10, p[0] + 18, p[1] + 22], fill=(10, 10, 12), outline=(80, 80, 90), width=3)
    # ponto de luz no forro ao lado
    q = cam.project((1.3, y - 0.002, 1.6))
    cv.rect(q[0] - 90, q[1] - 60, q[0] + 90, q[1] + 60, (252, 252, 250), tex=0.5)
    cv.glow(18, 245, 0.45)
    return cv.img


def wall_bg(cv: Canvas, color=(222, 216, 204), tex=6):
    cv.rect(0, 0, W, H, color, tex=tex, grad=(0.3, -1, 0.18))


def bullet_camera_wall(seed=0):
    cv = Canvas(seed=seed)
    wall_bg(cv, (214, 210, 200))
    cv.rect(560, 380, 720, 540, (238, 238, 236), tex=1)
    cv.rect(615, 300, 665, 400, (230, 230, 228), tex=1)
    cv.poly2([(470, 230), (900, 250), (900, 360), (470, 345)], (240, 240, 238), tex=1.5)
    cv.poly2([(430, 225), (480, 228), (480, 350), (430, 345)], (210, 210, 210), tex=1)
    cv.ellipse([300, 200, 470, 370], fill=(45, 45, 50))
    cv.ellipse([335, 235, 435, 335], fill=(15, 15, 20), outline=(90, 90, 100), width=4)
    cv.ellipse([360, 255, 395, 290], fill=(90, 100, 130))
    cv.draw.line([(900, 330), (1050, 360), (1080, 560), (1100, H)], fill=(30, 30, 30), width=8)
    return cv.img


def rack(seed=0):
    cv = Canvas(seed=seed)
    wall_bg(cv, (205, 205, 200))
    cv.rect(300, 40, 980, 930, (28, 28, 30), tex=2)
    cv.rect(330, 60, 950, 910, (45, 45, 48), tex=3)
    for x in (340, 925):
        for y in range(70, 900, 22):
            cv.draw.rectangle([x, y, x + 12, y + 10], fill=(20, 20, 22))
    rnd = random.Random(seed)
    y = 100
    # patch panel
    cv.rect(345, y, 935, y + 70, (60, 60, 64), tex=1)
    ports = []
    for i in range(24):
        px = 380 + i * 22
        cv.draw.rectangle([px, y + 25, px + 16, y + 45], fill=(15, 15, 15))
        ports.append((px + 8, y + 45))
    colors = [(40, 90, 200), (220, 200, 40), (200, 60, 50), (40, 160, 70), (230, 230, 230)]
    for px, py in ports:
        c = rnd.choice(colors)
        end = (px + rnd.randint(-60, 60), 330)
        cv.draw.line([(px, py), (px + rnd.randint(-10, 10), py + 60), end], fill=c, width=5)
    # switch
    y = 340
    cv.rect(345, y, 935, y + 60, (150, 152, 158), tex=1)
    for i in range(24):
        px = 380 + i * 22
        cv.draw.rectangle([px, y + 18, px + 16, y + 38], fill=(30, 30, 30))
        cv.draw.ellipse([px + 4, y + 44, px + 10, y + 50], fill=(60, 220, 90) if rnd.random() > 0.2 else (230, 160, 40))
    # NVR
    y = 440
    cv.rect(345, y, 935, y + 110, (22, 22, 24), tex=1)
    cv.text((380, y + 40), "NVR 16CH", 26, (190, 190, 200), "b")
    for i in range(6):
        cv.ellipse([700 + i * 30, y + 48, 712 + i * 30, y + 60], fill=(70, 140, 255))
    # nobreak / régua
    y = 590
    cv.rect(345, y, 935, y + 60, (35, 35, 38), tex=1)
    for i in range(8):
        cv.rrect([380 + i * 66, y + 15, 420 + i * 66, y + 45], 6, fill=(15, 15, 15))
    y = 690
    cv.rect(345, y, 935, y + 180, (30, 30, 32), tex=1)
    cv.text((640, y + 90), "UPS", 34, (120, 120, 130), "b", anchor="mm")
    cv.ellipse([860, y + 30, 880, y + 50], fill=(60, 220, 90))
    return cv.img


def workbench_camera(seed=0):
    cv = Canvas(seed=seed)
    for y in range(0, H, 6):
        t = (math.sin(y * 0.05) + 1) / 2
        cv.draw.line([(0, y), (W, y)], fill=mix((150, 110, 70), (175, 135, 90), t), width=6)
    cv.img = cv.img.filter(ImageFilter.GaussianBlur(1))
    cv.refresh()
    # câmera bullet deitada
    cv.rrect([380, 360, 820, 520], 60, fill=(235, 235, 232), outline=(180, 180, 180), width=3)
    cv.rrect([350, 350, 420, 530], 30, fill=(215, 215, 212))
    cv.ellipse([290, 375, 420, 505], fill=(40, 40, 45))
    cv.ellipse([320, 405, 390, 475], fill=(15, 15, 18), outline=(100, 100, 110), width=3)
    cv.rect(820, 420, 900, 460, (200, 200, 200), tex=1)
    cv.draw.line([(900, 440), (1000, 470), (1080, 600)], fill=(30, 30, 30), width=9)
    # tampa aberta e placa
    cv.rect(560, 560, 820, 700, (30, 110, 60), tex=4)
    for i in range(10):
        cv.rect(580 + i * 22, 600, 592 + i * 22, 640, (20, 20, 20), tex=1)
    # chave de fenda e multímetro
    cv.draw.line([(150, 760), (420, 650)], fill=(170, 170, 175), width=10)
    cv.draw.line([(60, 800), (170, 752)], fill=(230, 190, 30), width=34)
    cv.rrect([900, 640, 1130, 900], 20, fill=(230, 180, 30))
    cv.rect(930, 670, 1100, 740, (170, 185, 160), tex=1)
    cv.text((1015, 705), "12.0", 44, (30, 30, 30), "m", anchor="mm")
    cv.ellipse([975, 770, 1055, 850], fill=(40, 40, 40))
    return cv.img


def monitor_grid(seed=0, tiles=None, cols=3, rows=3, stamp="03/10/2026 10:41:07"):
    """Monitor do DVR/NVR com mosaico de câmeras. tiles: lista de (scene, label) ou ('nosignal', label)."""
    cv = Canvas(seed=seed)
    wall_bg(cv, (190, 185, 178))
    cv.rect(0, 820, W, H, (120, 90, 60), tex=8)
    cv.rect(110, 70, 1170, 760, (18, 18, 20), tex=1)
    sx0, sy0, sx1, sy1 = 140, 100, 1140, 730
    cv.rect(sx0, sy0, sx1, sy1, (5, 5, 8), tex=0.5)
    tw, th = (sx1 - sx0) // cols, (sy1 - sy0) // rows
    tiles = tiles or []
    for i in range(cols * rows):
        r, c = divmod(i, cols)
        x, y = sx0 + c * tw, sy0 + r * th
        if i < len(tiles):
            scene, label = tiles[i]
            if scene == "nosignal":
                t = Image.new("RGB", (tw - 4, th - 4), (20, 40, 140))
                d = ImageDraw.Draw(t)
                d.text(((tw - 4) / 2, (th - 4) / 2), "SEM SINAL", font=font(26, "b"), fill=(255, 255, 255), anchor="mm")
                d.text((8, 6), label, font=font(16, "m"), fill=(255, 255, 255))
            elif scene == "black":
                t = Image.new("RGB", (tw - 4, th - 4), (8, 8, 10))
            else:
                t = cctv_frame(scene, seed=seed + i, label=label, stamp=None, w=tw - 4, h=th - 4, tile=True)
            cv.img.paste(t, (x + 2, y + 2))
    cv.refresh()
    cv.draw.text((sx1 - 10, sy1 - 8), stamp, font=font(18, "m"), fill=(240, 240, 240), anchor="rd")
    cv.rect(560, 760, 720, 820, (25, 25, 28), tex=1)
    # reflexo
    cv.poly2([(160, 110), (520, 110), (300, 720), (160, 720)], (255, 255, 255), tex=0, alpha=18)
    return cv.img


# ============================================================================ predial (2D)
def luminaire_label(seed=0):
    cv = Canvas(seed=seed)
    cv.rect(0, 0, W, H, (232, 232, 230), tex=3, grad=(1, 1, 0.25))
    for y in range(60, H, 90):
        cv.draw.line([(0, y), (W, y + 10)], fill=(215, 215, 212), width=2)
    lab = Image.new("RGB", (760, 470), (250, 250, 248))
    d = ImageDraw.Draw(lab)
    d.rectangle([6, 6, 753, 463], outline=(30, 30, 30), width=4)
    d.text((30, 26), "LUMINÁRIA LED DE EMBUTIR 60x60", font=font(34, "b"), fill=(20, 20, 20))
    lines = [
        "Modelo: PL-6060-40W",
        "Potência: 40 W   |   4000 K",
        "Fluxo luminoso: 4.000 lm",
        "Tensão: 100-240 V~  50/60 Hz",
        "FP > 0,92   IRC > 80",
        "Lote: 2609-118   Fab.: 09/2026",
    ]
    for i, s in enumerate(lines):
        d.text((30, 90 + i * 44), s, font=font(28), fill=(30, 30, 30))
    rnd = random.Random(seed)
    x = 520
    while x < 730:
        wdt = rnd.choice([2, 3, 5])
        d.rectangle([x, 330, x + wdt, 430], fill=(15, 15, 15))
        x += wdt + rnd.choice([2, 3, 4])
    d.text((520, 436), "7 891234 560118", font=font(16, "m"), fill=(20, 20, 20))
    lab = lab.rotate(-4, expand=True, fillcolor=(0, 0, 0))
    mask = Image.new("L", (760, 470), 255).rotate(-4, expand=True, fillcolor=0)
    cv.img.paste(lab, (250, 230), mask)
    cv.refresh()
    return cv.img


def split_evaporator(seed=0, dirty=False):
    cv = Canvas(seed=seed)
    wall_bg(cv, (226, 220, 206))
    body = (242, 242, 240) if not dirty else (222, 218, 205)
    cv.rrect([200, 250, 1080, 540], 40, fill=body, outline=(200, 200, 198), width=3)
    cv.rect(220, 270, 1060, 300, mul(body, 0.97), tex=1)
    cv.rect(260, 470, 1020, 520, (70, 70, 74), tex=2)
    for x in range(270, 1020, 30):
        cv.draw.line([(x, 475), (x + 14, 515)], fill=(120, 120, 125), width=3)
    cv.rect(900, 330, 990, 380, (25, 25, 28), tex=1)
    cv.text((945, 355), "23", 34, (80, 200, 255), "m", anchor="mm")
    cv.ellipse([1000, 345, 1012, 357], fill=(60, 220, 90))
    cv.rect(1020, 540, 1070, H, (240, 240, 238), tex=1.5)
    if dirty:
        cv.rect(260, 470, 1020, 520, (40, 40, 38), tex=6, alpha=150)
        for _ in range(30):
            x = random.randint(260, 1020)
            cv.ellipse([x, 500, x + 8, 512], fill=(30, 40, 30))
    return cv.img


def ac_filter(seed=0, dirty=False):
    cv = Canvas(seed=seed)
    cv.rect(0, 0, W, H, (120, 95, 70), tex=8)
    frame = (205, 220, 230)
    cv.rrect([170, 160, 1110, 800], 18, fill=frame, outline=(150, 165, 175), width=4)
    mesh_bg = (232, 236, 238) if not dirty else (150, 148, 140)
    cv.rect(200, 190, 1080, 770, mesh_bg, tex=3 if not dirty else 14)
    step = 9
    col = (170, 180, 188) if not dirty else (110, 108, 100)
    for x in range(200, 1080, step):
        cv.draw.line([(x, 190), (x, 770)], fill=col, width=1)
    for y in range(190, 770, step):
        cv.draw.line([(200, y), (1080, y)], fill=col, width=1)
    for x in (493, 786):
        cv.rect(x - 6, 190, x + 6, 770, frame, tex=1)
    if dirty:
        for _ in range(60):
            cv.poly2([(random.randint(200, 1080), random.randint(190, 770)) for _ in range(6)], (95, 90, 80), tex=10, soft=8, alpha=120)
    return cv.img


def condenser(seed=0):
    cv = Canvas(seed=seed)
    cv.rect(0, 0, W, H, (196, 184, 168), tex=10)
    for y in range(0, H, 60):  # reboco com linhas sutis
        cv.draw.line([(0, y), (W, y)], fill=(185, 173, 158), width=1)
    cv.rect(220, 700, 1060, 730, (90, 90, 95), tex=2)
    cv.rect(260, 730, 290, 900, (90, 90, 95), tex=2)
    cv.rect(990, 730, 1020, 900, (90, 90, 95), tex=2)
    cv.rect(240, 260, 1040, 700, (236, 234, 226), tex=3)
    cx, cy, r = 520, 480, 190
    for k in range(10):
        rr = r - k * 18
        cv.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(150, 150, 150), width=4)
    for a in range(0, 360, 30):
        cv.draw.line([(cx, cy), (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))], fill=(150, 150, 150), width=3)
    cv.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], fill=(60, 60, 60))
    for y in range(300, 680, 14):
        cv.draw.line([(800, y), (1010, y)], fill=(200, 198, 190), width=5)
    cv.draw.line([(1040, 600), (1120, 600), (1120, 120)], fill=(30, 30, 30), width=26)
    cv.draw.line([(1040, 640), (1150, 640), (1150, 120)], fill=(170, 110, 70), width=12)
    return cv.img


def door_closer(seed=0, close=False):
    cv = Canvas(seed=seed)
    wall_bg(cv, (224, 218, 204))
    if not close:
        cv.rect(390, 60, 890, H, (240, 240, 236), tex=1)
        cv.rect(420, 90, 860, H, (140, 102, 66), tex=9, grad=(1, 0, 0.15))
        cv.rect(800, 520, 830, 600, (200, 200, 205), tex=1)
        cv.rrect([450, 110, 640, 160], 10, fill=(170, 172, 178), outline=(120, 120, 125), width=2)
        cv.draw.line([(620, 135), (720, 95), (840, 82)], fill=(150, 152, 158), width=12)
        cv.rect(800, 66, 880, 90, (165, 165, 170), tex=1)
        cv.rect(0, 880, W, H, (150, 140, 128), tex=6)
    else:
        cv.rect(0, 0, W, 300, (240, 240, 236), tex=1)
        cv.rect(0, 300, W, H, (140, 102, 66), tex=9)
        cv.rrect([150, 380, 840, 590], 30, fill=(178, 180, 186), outline=(110, 110, 115), width=4)
        for x in (200, 790):
            cv.ellipse([x - 18, 470, x + 18, 506], fill=(130, 130, 135), outline=(90, 90, 95), width=2)
        cv.text((495, 485), "MA-200", 34, (90, 90, 96), "b", anchor="mm")
        cv.draw.line([(780, 450), (1000, 300), (1200, 260)], fill=(150, 152, 158), width=34)
        cv.ellipse([760, 430, 810, 480], fill=(120, 120, 125))
        cv.ellipse([980, 280, 1020, 320], fill=(120, 120, 125))
        cv.rect(1120, 230, 1280, 290, (165, 165, 170), tex=1)
    return cv.img


def outlet_plate(cv: Canvas, x, y, burned=False):
    cv.rrect([x, y, x + 150, y + 230], 16, fill=(246, 246, 244), outline=(200, 200, 200), width=2)
    for k in (0, 1):
        cy = y + 62 + k * 104
        cx = x + 75
        pts = [(cx + 46 * math.cos(math.radians(a)), cy + 40 * math.sin(math.radians(a))) for a in range(0, 360, 60)]
        cv.draw.polygon(pts, fill=(232, 232, 230), outline=(190, 190, 190))
        for dx, dy in ((-16, -6), (16, -6), (0, 16)):
            cv.ellipse([cx + dx - 6, cy + dy - 6, cx + dx + 6, cy + dy + 6], fill=(40, 40, 40))
    if burned:
        cv.poly2([(x + 30, y + 10), (x + 140, y + 30), (x + 130, y + 140), (x + 40, y + 120)], (35, 25, 20), tex=12, soft=14, alpha=210)
        cv.poly2([(x + 60, y - 40), (x + 120, y - 50), (x + 110, y + 40), (x + 70, y + 30)], (60, 50, 45), tex=12, soft=20, alpha=160)


def outlets(seed=0, burned=False):
    cv = Canvas(seed=seed)
    wall_bg(cv, (236, 234, 228))
    cv.rect(0, 820, W, 860, (200, 195, 185), tex=2)
    cv.rect(0, 860, W, H, (150, 140, 125), tex=7)
    if burned:
        outlet_plate(cv, 520, 380, burned=True)
    else:
        for x in (300, 560, 820):
            outlet_plate(cv, x, 380)
    return cv.img


def breaker_panel(seed=0):
    cv = Canvas(seed=seed)
    wall_bg(cv, (220, 216, 206))
    cv.rect(300, 120, 900, 860, (150, 152, 156), tex=3)
    cv.rect(330, 150, 870, 830, (205, 205, 208), tex=2)
    cv.poly2([(900, 120), (1150, 170), (1150, 820), (900, 860)], (140, 142, 146), tex=3)
    cv.poly2([(930, 150), (1120, 190), (1120, 800), (930, 830)], (165, 167, 170), tex=2)
    rnd = random.Random(seed)
    wires = [(200, 40, 40), (40, 80, 200), (40, 150, 60), (30, 30, 30)]
    for row, y in enumerate((230, 420, 610)):
        cv.rect(350, y + 40, 850, y + 60, (170, 170, 172), tex=1)
        for i in range(12):
            x = 365 + i * 40
            cv.rect(x, y, x + 34, y + 110, (245, 245, 243), tex=1)
            cv.rect(x + 10, y + 40, x + 24, y + 70, (30, 30, 30), tex=1)
            cv.draw.line([(x + 17, y), (x + 17 + rnd.randint(-20, 20), y - 50)], fill=rnd.choice(wires), width=5)
            cv.draw.line([(x + 17, y + 110), (x + 17 + rnd.randint(-20, 20), y + 160)], fill=rnd.choice(wires), width=5)
            cv.text((x + 17, y + 95), str(row * 12 + i + 1), 13, (60, 60, 60), "c", anchor="mm")
    return cv.img


def under_sink_leak(seed=0):
    cv = Canvas(seed=seed)
    cv.rect(0, 0, W, H, (230, 225, 215), tex=4)
    cv.rect(140, 80, 1140, 900, (120, 85, 55), tex=6)
    cv.rect(180, 120, 1100, 880, (60, 45, 32), tex=8, grad=(0, 1, 0.3))
    cv.rect(180, 700, 1100, 880, (95, 70, 48), tex=8)
    pipe = (240, 240, 238)
    cv.rect(610, 120, 660, 420, pipe, tex=1)
    cv.draw.arc([560, 360, 760, 560], 0, 180, fill=pipe, width=50)
    cv.rect(710, 330, 760, 460, pipe, tex=1)
    cv.draw.line([(760, 345), (1100, 345)], fill=pipe, width=46)
    cv.rect(600, 400, 670, 425, (200, 200, 200), tex=1)
    # gotas e poça
    for dy in range(470, 690, 40):
        cv.ellipse([628, dy, 642, dy + 18], fill=(160, 190, 210))
    cv.poly2([(470, 760), (760, 740), (900, 790), (700, 840), (480, 820)], (120, 140, 150), tex=4, soft=6, alpha=200)
    cv.poly2([(560, 770), (700, 765), (720, 790), (590, 800)], (210, 225, 235), tex=2, soft=4, alpha=200)
    cv.rect(300, 720, 430, 860, (40, 90, 170), tex=3)  # balde
    return cv.img


def valve(seed=0):
    cv = Canvas(seed=seed)
    cv.rect(0, 0, W, H, (238, 240, 240), tex=3)
    for x in range(0, W, 200):
        cv.draw.line([(x, 0), (x, H)], fill=(205, 208, 210), width=4)
    for y in range(0, H, 200):
        cv.draw.line([(0, y), (W, y)], fill=(205, 208, 210), width=4)
    cv.ellipse([470, 310, 810, 650], fill=(200, 202, 208), outline=(150, 152, 158), width=4)
    cv.ellipse([560, 400, 720, 560], fill=(170, 172, 178))
    cv.rect(615, 340, 665, 620, (215, 217, 222), tex=1)
    cv.rect(500, 455, 780, 505, (215, 217, 222), tex=1)
    cv.ellipse([610, 450, 670, 510], fill=(30, 90, 200))
    return cv.img


# ============================================================================ alarme
def alarm_panel(seed=0, lcd="SISTEMA PRONTO"):
    cv = Canvas(seed=seed)
    wall_bg(cv, (220, 214, 200))
    cv.rect(160, 200, 600, 760, (225, 220, 205), tex=3)
    cv.rect(180, 220, 580, 740, (235, 230, 216), tex=2)
    cv.text((380, 300), "CENTRAL DE", 30, (60, 60, 60), "b", anchor="mm")
    cv.text((380, 340), "ALARME", 30, (60, 60, 60), "b", anchor="mm")
    cv.ellipse([360, 660, 400, 700], fill=(60, 220, 90))
    keypad(cv, 740, 260, lcd)
    cv.draw.line([(380, 760), (380, H)], fill=(240, 240, 240), width=18)
    return cv.img


def keypad(cv: Canvas, x, y, lcd="SISTEMA PRONTO", scale=1.0):
    s = scale
    cv.rrect([x, y, x + 330 * s, y + 440 * s], int(26 * s), fill=(246, 246, 244), outline=(190, 190, 190), width=3)
    cv.rect(x + 30 * s, y + 40 * s, x + 300 * s, y + 130 * s, (150, 200, 120), tex=2)
    cv.text((x + 165 * s, y + 70 * s), lcd[:16], int(24 * s), (20, 40, 20), "m", anchor="mm")
    cv.text((x + 165 * s, y + 104 * s), "03/10 10:42", int(20 * s), (20, 40, 20), "m", anchor="mm")
    keys = "123456789*0#"
    for i, k in enumerate(keys):
        r, c = divmod(i, 3)
        kx = x + 45 * s + c * 85 * s
        ky = y + 160 * s + r * 65 * s
        cv.rrect([kx, ky, kx + 70 * s, ky + 50 * s], int(10 * s), fill=(225, 225, 222), outline=(180, 180, 180))
        cv.text((kx + 35 * s, ky + 25 * s), k, int(24 * s), (50, 50, 50), "b", anchor="mm")


def keypad_closeup(seed=0, lcd="SISTEMA OK"):
    cv = Canvas(seed=seed)
    wall_bg(cv, (222, 216, 204))
    keypad(cv, 340, 120, lcd, scale=1.6)
    return cv.img


def motion_sensor(seed=0, old=False):
    cv = Canvas(seed=seed)
    cv.rect(0, 0, W / 2, H, (232, 226, 214), tex=5, grad=(1, 0, 0.1))
    cv.rect(W / 2, 0, W, H, (205, 199, 187), tex=5, grad=(-1, 0, 0.1))
    cv.rect(0, 0, W, 120, (240, 240, 238), tex=2)
    body = (250, 250, 248) if not old else (220, 205, 165)
    cv.rrect([480, 220, 800, 640], 50, fill=body, outline=(190, 190, 185), width=3)
    lens = (225, 225, 228) if not old else (185, 175, 145)
    cv.rrect([520, 420, 760, 610], 40, fill=lens)
    for x in range(540, 760, 30):
        cv.draw.line([(x, 425), (x, 605)], fill=mul(lens, 0.9), width=2)
    for y in range(440, 610, 30):
        cv.draw.line([(525, y), (755, y)], fill=mul(lens, 0.9), width=2)
    cv.ellipse([628, 300, 652, 324], fill=(235, 40, 40) if not old else (90, 40, 40))
    cv.text((640, 370), "IVP", 30, (120, 120, 120), "b", anchor="mm")
    if old:
        cv.draw.line([(560, 450), (640, 540), (700, 520)], fill=(90, 80, 60), width=3)
        for _ in range(25):
            x, y = random.randint(490, 790), random.randint(230, 630)
            cv.ellipse([x, y, x + 10, y + 7], fill=(150, 135, 100))
    return cv.img


def power_supply_box(seed=0):
    cv = Canvas(seed=seed)
    wall_bg(cv, (210, 206, 196))
    cv.rect(260, 160, 1020, 820, (238, 238, 236), tex=2)
    cv.rect(290, 190, 990, 790, (215, 215, 212), tex=3)
    cv.rect(380, 300, 900, 600, (190, 192, 196), tex=2)
    for x in range(400, 880, 22):
        cv.rect(x, 320, x + 10, 400, (120, 122, 126), tex=1)
    cv.rect(460, 440, 820, 560, (250, 250, 248), tex=1)
    cv.text((640, 470), "FONTE 12V 5A", 34, (30, 30, 30), "b", anchor="mm")
    cv.text((640, 520), "entrada 100-240V~", 22, (60, 60, 60), "r", anchor="mm")
    cv.draw.line([(500, 600), (480, 720), (420, 790)], fill=(200, 40, 40), width=8)
    cv.draw.line([(530, 600), (520, 720), (470, 790)], fill=(25, 25, 25), width=8)
    cv.draw.line([(780, 600), (800, 700), (900, 790)], fill=(25, 25, 25), width=10)
    return cv.img


def panic_button(seed=0):
    cv = Canvas(seed=seed)
    for y in range(0, H, 5):
        t = (math.sin(y * 0.07) + 1) / 2
        cv.draw.line([(0, y), (W, y)], fill=mix((95, 70, 48), (120, 90, 62), t), width=5)
    cv.refresh()
    cv.rect(0, 700, W, H, (40, 35, 32), tex=4)
    cv.rrect([480, 330, 800, 560], 20, fill=(235, 235, 232), outline=(180, 180, 180), width=3)
    cv.ellipse([560, 370, 720, 530], fill=(200, 30, 30), outline=(140, 20, 20), width=6)
    cv.text((640, 450), "PÂNICO", 22, (255, 255, 255), "b", anchor="mm")
    return cv.img


# ============================================================================ documentos fotografados
def paper_photo(title, rows, seed=0, signed=True, footer="Assinatura do responsável pela agência"):
    rnd = random.Random(seed)
    bg = Canvas(seed=seed)
    for y in range(0, H, 6):
        t = (math.sin(y * 0.04) + 1) / 2
        bg.draw.line([(0, y), (W, y)], fill=mix((120, 90, 60), (140, 105, 72), t), width=6)
    sheet = Image.new("RGB", (820, 1080), (248, 247, 242))
    d = ImageDraw.Draw(sheet)
    d.text((410, 70), title, font=font(30, "b"), fill=(20, 20, 20), anchor="mm")
    d.line([(60, 110), (760, 110)], fill=(40, 40, 40), width=2)
    y = 150
    for k, v in rows:
        d.text((60, y), f"{k}:", font=font(22, "b"), fill=(30, 30, 30))
        d.text((300, y), str(v), font=font(22), fill=(30, 30, 30))
        y += 46
    y += 20
    for s in ("Declaramos que o serviço acima foi executado e", "conferido no local, nas condições descritas."):
        d.text((60, y), s, font=font(20), fill=(40, 40, 40))
        y += 32
    d.line([(100, 900), (720, 900)], fill=(30, 30, 30), width=2)
    d.text((410, 925), footer, font=font(18), fill=(60, 60, 60), anchor="mm")
    if signed:
        pts = []
        x = 180
        while x < 560:
            pts.append((x, 860 + 25 * math.sin(x * 0.05) + rnd.uniform(-10, 10)))
            x += 12
        d.line(pts, fill=(20, 40, 140), width=4)
        d.ellipse([520, 760, 700, 880], outline=(60, 80, 170), width=4)
        d.text((610, 820), "AG.", font=font(26, "b"), fill=(60, 80, 170), anchor="mm")
    sheet = sheet.resize((700, 922))
    rot = rnd.uniform(-5, 5)
    sh = Image.new("L", sheet.size, 255).rotate(rot, expand=True, fillcolor=0)
    shadow = Image.new("RGB", sh.size, (40, 30, 20))
    bg.img.paste(shadow, (300, 40), sh.filter(ImageFilter.GaussianBlur(10)))
    sheet = sheet.rotate(rot, expand=True, fillcolor=(0, 0, 0))
    bg.img.paste(sheet, (285, 20), sh)
    return bg.img


def removed_items(seed=0, kind="tubes"):
    """Caixa de papelão com lâmpadas/luminárias antigas retiradas."""
    rnd = random.Random(seed)
    cv = Canvas(seed=seed)
    cv.rect(0, 0, W, H, (150, 145, 138), tex=9)
    for y in range(0, H, 120):
        cv.draw.line([(0, y), (W, y + 6)], fill=(135, 130, 124), width=3)
    cv.poly2([(180, 420), (1100, 400), (1160, 900), (130, 920)], (176, 136, 92), tex=10)
    cv.poly2([(180, 420), (1100, 400), (1060, 330), (230, 350)], (196, 156, 108), tex=8)
    for k in range(rnd.randint(5, 9)):
        y = 380 + k * 34 + rnd.randint(-8, 8)
        x0, x1 = 160 + rnd.randint(-30, 30), 1120 + rnd.randint(-30, 30)
        cv.draw.line([(x0, y), (x1, y + rnd.randint(-25, 25))], fill=(238, 238, 232), width=26)
        cv.draw.line([(x0, y - 6), (x1, y - 6)], fill=(250, 250, 248), width=6)
        cv.rect(x0 - 18, y - 13, x0 + 6, y + 13, (90, 90, 95), tex=1)
        cv.rect(x1 - 6, y - 13, x1 + 18, y + 13, (90, 90, 95), tex=1)
    if kind == "fixtures":
        for k in range(3):
            x = 260 + k * 260
            cv.rect(x, 560, x + 230, 860, (200, 200, 196), tex=3)
            cv.rect(x + 20, 580, x + 210, 840, (175, 175, 170), tex=2)
    return cv.img
