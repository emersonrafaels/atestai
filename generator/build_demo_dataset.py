"""Gera o dataset sintético do Atest.AI em ../dados.

    python build_demo_dataset.py            # gera tudo
    python build_demo_dataset.py --limpar   # apaga ../dados antes

Saída:
    data/references/   LPU por esteira, checklist por tipo de serviço, régua do score
    data/tickets/<id>/ chamado.json (formato de extração do Salesforce) + anexos/
    data/history/<id>/ chamados antigos usados no índice de fotos (detecção de reaproveitamento)
    data/ground_truth/<id>.json  resposta esperada (rótulos de itens, fotos, checklist, score e recomendação)
"""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import random
import os
import shutil
import stat
import sys
import time
from pathlib import Path

import piexif
from PIL import Image, ImageEnhance

sys.path.insert(0, str(Path(__file__).parent))
import scenes  # noqa: E402
from camera import photograph  # noqa: E402
from cases import CASES, HISTORY, LPU, SUPPLIER  # noqa: E402
from quotes import make_xlsx, total  # noqa: E402
import real_photos  # noqa: E402
from real_photos import real_photo  # noqa: E402
from render import H, W, finish, illegible  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "data"

SCENES = {
    "backoffice": scenes.backoffice,
    "ceiling_view": scenes.ceiling_view,
    "bathroom": scenes.bathroom,
    "storage": scenes.storage,
    "facade": scenes.facade,
    "cctv_frame": scenes.cctv_frame,
    "dome_camera": scenes.dome_camera,
    "rack": scenes.rack,
    "workbench_camera": scenes.workbench_camera,
    "monitor_grid": scenes.monitor_grid,
    "luminaire_label": scenes.luminaire_label,
    "split_evaporator": scenes.split_evaporator,
    "ac_filter": scenes.ac_filter,
    "condenser": scenes.condenser,
    "door_closer": scenes.door_closer,
    "outlets": scenes.outlets,
    "breaker_panel": scenes.breaker_panel,
    "under_sink_leak": scenes.under_sink_leak,
    "valve": scenes.valve,
    "alarm_panel": scenes.alarm_panel,
    "keypad_closeup": scenes.keypad_closeup,
    "motion_sensor": scenes.motion_sensor,
    "power_supply_box": scenes.power_supply_box,
    "panic_button": scenes.panic_button,
    "removed_items": scenes.removed_items,
    "bullet_camera_wall": scenes.bullet_camera_wall,
}


def _cctv_background(scene, seed, size, tile):
    """Fundo da imagem de CFTV vindo das fotos reais: o quadro inteiro usa uma foto só dele; os quadros pequenos do
    mosaico podem repetir foto entre chamados."""
    kw = {"scene": scene}
    return real_photos.background("cctv_view", kw, seed, size) if tile else real_photo("cctv_view", kw, seed, size)


scenes.CCTV_BACKGROUND = _cctv_background
PHONES = [("samsung", "SM-A546E"), ("motorola", "moto g54 5G"), ("Xiaomi", "Redmi Note 13"), ("samsung", "SM-A155M")]


def exif_bytes(data, seed):
    if not data:
        return None
    make, model = PHONES[seed % len(PHONES)]
    z = {
        piexif.ImageIFD.Make: make.encode(),
        piexif.ImageIFD.Model: model.encode(),
        piexif.ImageIFD.DateTime: data.encode(),
        piexif.ImageIFD.Software: b"camera",
    }
    e = {piexif.ExifIFD.DateTimeOriginal: data.encode(), piexif.ExifIFD.DateTimeDigitized: data.encode()}
    return piexif.dump({"0th": z, "Exif": e, "GPS": {}, "1st": {}, "thumbnail": None})


def save_jpg(img, path, data, seed, quality=85):
    ex = exif_bytes(data, seed)
    kw = {"quality": quality}
    if ex:
        kw["exif"] = ex
    img.save(path, **kw)


def apply_framing(img, seed):
    """Variação de enquadramento do celular (zoom, deslocamento, inclinação): evita fotos sintéticas quase iguais
    entre chamados diferentes, o que geraria falso 'reaproveitamento' no índice de hashes."""
    r = random.Random(seed * 7 + 3)
    z = r.uniform(1.0, 1.16)
    ang = r.uniform(-3.5, 3.5)
    w, h = img.size
    cw, ch = w / z, h / z
    x0 = r.uniform(0, w - cw)
    y0 = r.uniform(0, h - ch)
    out = img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).resize((w, h), Image.BICUBIC)
    return out.rotate(ang, resample=Image.BICUBIC, expand=False, fillcolor=(40, 40, 40)).crop((24, 18, w - 24, h - 18)).resize((w, h))


def render_scene(name, kwargs, seed):
    illeg = name.startswith("UNREADABLE:")
    if illeg:
        name = name.split(":", 1)[1]
    kw = dict(kwargs)
    kw.setdefault("seed", seed)
    framing = kw.pop("framing", seed)
    real = real_photo(name, kw, kw["seed"], (W, H))  # data/real_photos/<chave>/, se houver
    if real is not None:
        img = apply_framing(real, framing)
    else:
        img = SCENES[name](**kw)
        img = apply_framing(img, framing)
        rnd = random.Random(seed)
        img = finish(img, seed=seed, exposure=rnd.uniform(0.94, 1.05), warm=rnd.uniform(-0.03, 0.05), vignette=rnd.uniform(0.25, 0.4))
        img = photograph(img, seed, screen=name in ("cctv_frame", "monitor_grid"))
    if illeg:
        img = illegible(img, seed=seed)
    return img


def attachment_meta(path: Path, data_upload: str, by="supplier"):
    ct = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix == ".xlsx":
        ct = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return {"file_name": path.name, "content_type": ct, "size_bytes": path.stat().st_size, "sent_by": by, "data_upload": data_upload}


def ticket_json(c, attachments, value=None, status="forwarded_to_backoffice"):
    code, name, area = c["branch"]
    fn, cnpj, _ = SUPPLIER[c["supplier"]]
    return {
        "ticket_id": c["id"],
        "workstream": c["workstream"],
        "maintenance_type": c["maintenance_type"],
        "moment": c["moment"],
        "category": c["category"],
        "symptom": c["symptom"],
        "branch": {"code": code, "name": name, "environment": area},
        "supplier": {"name": fn, "cnpj": cnpj},
        "requested_scope": c["scope"],
        "quoted_value": value,
        "dates": c["dates"],
        "status": status,
        "manager": {"first_check": "forwarded", "note": ""},
        "dataset": c.get("dataset", "scenarios"),  # casos do deck ficam junto com os cenários de teste
        "attachments": attachments,
    }


def build_references():
    ref = ROOT / "references"
    ref.mkdir(parents=True, exist_ok=True)
    for st, rows in LPU.items():
        with open(ref / f"lpu_{st.lower()}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["code", "description", "unit", "reference_price"])
            for r in rows:
                w.writerow([r[0], r[1], r[2], f"{r[3]:.2f}"])


def build_history():
    paths = {}
    for h in HISTORY:
        d = ROOT / "history" / h["id"] / "attachments"
        d.mkdir(parents=True, exist_ok=True)
        attachments, paths[h["id"]] = [], []
        for file, scene, kw, data in h["photos"]:
            seed = kw.get("seed", 0)
            img = render_scene(scene, kw, seed)
            p = d / file
            save_jpg(img, p, data, seed)
            paths[h["id"]].append(p)
            attachments.append(attachment_meta(p, h["dates"]["supplier_submission"]))
        cj = ticket_json(h, attachments, status=h["status_final"])
        (d.parent / "ticket.json").write_text(json.dumps(cj, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def reuse(src: Path, dst: Path, data, variant: int):
    img = Image.open(src).convert("RGB")
    w, h = img.size
    if variant == 0:  # reenviada por WhatsApp: recompressão, redimensionamento, sem EXIF
        img = img.crop((int(w * 0.02), int(h * 0.02), int(w * 0.98), int(h * 0.98))).resize((1200, 900))
        img.save(dst, quality=68)
    else:  # recorte leve + brilho, mantém a data original no EXIF
        img = img.crop((int(w * 0.04), 0, w, int(h * 0.97))).resize((1280, 960))
        img = ImageEnhance.Brightness(img).enhance(1.05)
        save_jpg(img, dst, data, 7, quality=82)


def build_cases(hist):
    for c in CASES:
        base = ROOT / "tickets" / c["id"]
        attachments_dir = base / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        attachments = []
        up = c["dates"]["supplier_submission"]
        # orçamento: sempre a planilha padrão em Excel
        p = attachments_dir / f"Orcamento_{c['quote_number']}.xlsx"
        make_xlsx(p, c)
        attachments.append(attachment_meta(p, up))
        attachment_labels = {
            p.name: {
                "category": "quote_doc",
                "moment": "undetermined",
                "matches_scope": True,
                "readable": True,
                "description": "Orçamento (planilha Excel padrão)",
            }
        }
        # fotos
        for file, scene, kw, data, rot in c["photos"]:
            dst = attachments_dir / file
            if scene.startswith("REUSED:"):
                _, hid, idx = scene.split(":")
                reuse(hist[hid][int(idx)], dst, data, int(idx))
                rot = dict(rot, reused_from=f"{hid}/{hist[hid][int(idx)].name}")
            else:
                seed = kw.get("seed", 0)
                save_jpg(render_scene(scene, kw, seed), dst, data, seed)
            if not rot["readable"]:
                rot = dict(rot, matches_scope=None)
            attachments.append(attachment_meta(dst, up))
            attachment_labels[file] = rot
        for file, kind, data, rot in c.get("documents", []):
            dst = attachments_dir / file
            code, name, _ = c["branch"]
            supplier = SUPPLIER[c["supplier"]][0][:32]
            if kind == "report":
                img = scenes.paper_photo(
                    "RELATÓRIO DE MANUTENÇÃO PREVENTIVA",
                    [
                        ("Chamado", c["id"]),
                        ("Agência", f"{name} ({code})"),
                        ("Fornecedor", supplier),
                        ("Câmeras testadas", "8 de 8 — OK"),
                        ("Sensores testados", "12 de 12 — OK"),
                        ("Central / NVR", "OK — gravação 30 dias"),
                        ("Data", "03/10/2026"),
                    ],
                    seed=77,
                    footer="Assinatura do técnico e da agência",
                )
            else:
                img = scenes.paper_photo(
                    "TERMO DE CONCLUSÃO DE SERVIÇO",
                    [
                        ("Chamado", c["id"]),
                        ("Agência", f"{name} ({code})"),
                        ("Fornecedor", supplier),
                        ("Serviço", c["scope"][:34] + "…"),
                        ("Data", "07/10/2026"),
                    ],
                    seed=78,
                )
            save_jpg(photograph(finish(img, seed=77), 77, paper=True), dst, data, 77)
            attachments.append(attachment_meta(dst, up))
            attachment_labels[file] = rot
        value = total(c)
        cj = ticket_json(c, attachments, value=c.get("ticket_value", value))
        (base / "ticket.json").write_text(json.dumps(cj, ensure_ascii=False, indent=2), encoding="utf-8")
        # gabarito
        lpu_idx = {r[0]: r for r in LPU[c["workstream"]]}
        items = []
        for n, (desc, un, q, u, rot) in enumerate(c["items"], 1):
            ref = lpu_idx[rot["lpu"]][3]
            items.append(
                {
                    "n": n,
                    "description": desc,
                    "unit": un,
                    "quantity": q,
                    "unit_value": u,
                    "total_value": round(q * u, 2),
                    "classification": rot["classification"],
                    "lpu_code": rot["lpu"],
                    "reference_price": ref,
                    "findings": rot["findings"],
                    "optional_findings": rot["optional"],
                    "expected_quantity_max": rot["qmax"],
                }
            )
        gt = {
            "ticket_id": c["id"],
            "workstream": c["workstream"],
            "moment": c["moment"],
            "maintenance_type": c["maintenance_type"],
            "category": c["category"],
            "symptom": c["symptom"],
            "before_applicable": c["service_type"] != "preventive_security",
            "dataset": "scenarios",
            "quoted_value": value,
            "items": items,
            "attachments": attachment_labels,
        }
        gt.update(c["expected"])
        (ROOT / "ground_truth").mkdir(exist_ok=True)
        (ROOT / "ground_truth" / f"{c['id']}.json").write_text(json.dumps(gt, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"  {c['id']}  {c['workstream']}  {c['category']:<20} R$ {value:>9,.2f}  {len(attachments)} anexos  → {c['expected']['recommendation']}"
        )


def contact_sheet(dest: Path):
    from PIL import ImageDraw
    from render import font

    thumbs = []
    for c in CASES:
        for a in sorted((ROOT / "tickets" / c["id"] / "attachments").iterdir()):
            if a.suffix.lower() in (".jpg", ".jpeg"):
                t = Image.open(a).convert("RGB").resize((320, 240))
                d = ImageDraw.Draw(t)
                d.rectangle([0, 0, 320, 22], fill=(0, 0, 0))
                d.text((5, 3), f"{c['id']} · {a.name[:26]}", font=font(13), fill=(255, 255, 255))
                thumbs.append(t)
    cols = 6
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 320, rows * 240), (255, 255, 255))
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * 320, (i // cols) * 240))
    sheet.save(dest, quality=82)


def rmtree_retry(p: Path, tries: int = 10) -> None:
    """Apaga a pasta. No OneDrive (ou com o painel aberto) arquivos podem ficar somente leitura ou presos por um
    instante: tira o atributo e tenta de novo. Se não conseguir, falha, em vez de deixar chamados pela metade."""

    def writable(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    for i in range(tries):
        if not p.exists():
            return
        try:
            shutil.rmtree(p, onexc=writable)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.5 * (i + 1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true")
    a = ap.parse_args()
    if a.clean:
        for sub in ("tickets", "history", "ground_truth", "references"):
            rmtree_retry(ROOT / sub)
    build_references()
    hist = build_history()
    build_cases(hist)
    contact_sheet(ROOT / "contact_sheet.jpg")
    print("ok →", ROOT)
