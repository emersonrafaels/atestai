"""Gerador: fotos reais por cena (data/real_photos/<chave>/) e simulação de câmera."""

import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))
import real_photos  # noqa: E402
from camera import photograph  # noqa: E402


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setattr(real_photos, "ROOT", tmp_path)
    monkeypatch.setattr(real_photos, "_ledger", None)
    (tmp_path / "outlets__burned").mkdir()
    for i, color in enumerate([(200, 40, 40), (40, 200, 40)]):
        Image.new("RGB", (2000, 1000), color).save(tmp_path / "outlets__burned" / f"{i}.jpg")
    return tmp_path


def test_scene_key():
    assert real_photos.key("outlets", {"burned": True}) == "outlets__burned"
    assert real_photos.key("outlets", {}) == "outlets"
    assert real_photos.key("backoffice", {"view": "C", "stains": True}) == "backoffice__stains"
    assert real_photos.key("ceiling_view", {"lights": "led"}) == "ceiling_view__led"
    # toda chave que o gerador pode pedir tem descrição para o modelo de imagem
    for name, kw in [("door_closer", {"close": True}), ("ac_filter", {"dirty": True}), ("motion_sensor", {"old": True}), ("removed_items", {})]:
        assert real_photos.key(name, kw) in real_photos.CATALOG


def test_each_photo_goes_to_one_ticket(folder):
    a = real_photos.real_photo("outlets", {"burned": True}, 1, (640, 480))
    b = real_photos.real_photo("outlets", {"burned": True}, 2, (640, 480))
    assert a.size == b.size == (640, 480) and a.getpixel((5, 5)) != b.getpixel((5, 5))
    assert real_photos.real_photo("outlets", {"burned": True}, 1, (640, 480)).getpixel((5, 5)) == a.getpixel((5, 5))  # mesma semente, mesma foto
    assert real_photos.real_photo("outlets", {"burned": True}, 3, (640, 480)) is None  # esgotou: volta para o desenho
    assert real_photos.real_photo("outlets", {}, 1, (640, 480)) is None  # pasta da variante sem queima não existe
    assert real_photos.real_photo("cctv_frame", {}, 1, (640, 480)) is None  # tela do CFTV fica sempre desenhada
    real_photos._ledger.save()
    assert (folder / "_usage.json").exists() and real_photos.status()["outlets__burned"] == (2, 2)


@pytest.fixture
def profile_reset():
    yield
    real_photos.use_profile("default")


def test_itau_profile_switches_folder_style_and_catalog(profile_reset):
    real_photos.use_profile("itau")
    assert real_photos.ROOT.name == "real_photos_itau" and "Itaú" in real_photos.STYLE
    assert "Itaú" in real_photos.CATALOG["facade"] and set(real_photos.PROFILES["default"][2]) <= set(real_photos.CATALOG)
    real_photos.use_profile("default")
    assert real_photos.ROOT.name == "real_photos" and "no readable brand names" in real_photos.STYLE


def test_every_scene_of_the_service_templates_has_an_itau_description():
    from build_validation_dataset import MODELS, OTHER_ROOMS

    asked = [(f["scene"], f["kw"]) for m in MODELS for f in m.before + m.after] + [(s, {}) for s, _ in OTHER_ROOMS]
    asked += [("cctv_view", {"scene": s}) for s in ("atm", "corridor", "parking", "office")]
    for name, kw in asked:
        if name not in real_photos.ALWAYS_DRAWN:
            assert real_photos.key(name, kw) in real_photos.CATALOG_ITAU, (name, kw)


def test_strict_and_record_modes(folder, profile_reset):
    real_photos.use_profile("default", mode="record")
    assert real_photos.real_photo("outlets", {"burned": True}, 1, (64, 48)) is None
    real_photos.real_photo("outlets", {"burned": True}, 1, (64, 48))  # mesma semente não conta duas vezes
    real_photos.real_photo("outlets", {"burned": True}, 2, (64, 48))
    real_photos.background("cctv_view", {"scene": "atm"}, 7, (64, 48))
    real_photos.background("cctv_view", {"scene": "atm"}, 8, (64, 48))  # fundo reaproveitável: basta uma foto
    assert real_photos.needs() == {"cctv_view__atm": 1, "outlets__burned": 2}

    real_photos.use_profile("default", mode="strict")
    real_photos.ROOT = folder  # o use_profile volta para data/real_photos; o teste usa a pasta temporária
    assert real_photos.real_photo("outlets", {"burned": True}, 1, (64, 48)) is not None
    assert real_photos.real_photo("outlets", {"burned": True}, 2, (64, 48)) is not None
    with pytest.raises(real_photos.PhotoShortage):
        real_photos.real_photo("outlets", {"burned": True}, 3, (64, 48))  # esgotou
    with pytest.raises(real_photos.PhotoShortage):
        real_photos.real_photo("valve", {}, 1, (64, 48))  # pasta não existe


def test_cctv_frame_uses_background_and_keeps_the_text(monkeypatch):
    import scenes

    plain = Image.new("RGB", (320, 240), (90, 140, 200))
    monkeypatch.setattr(scenes, "CCTV_BACKGROUND", lambda scene, seed, size, tile: plain.resize(size))
    a = scenes.cctv_frame("atm", seed=1, label="CAM 03", stamp="01/11/2026 10:00:00", w=320, h=240)
    b = scenes.cctv_frame("atm", seed=1, label="", stamp="", w=320, h=240)
    assert a.size == (320, 240) and a.tobytes() != b.tobytes()  # o texto continua desenhado por cima da foto


def test_camera_simulation_is_deterministic():
    base = Image.new("RGB", (320, 240), (200, 200, 190))
    a, b = photograph(base, 5), photograph(base, 5)
    assert a.size == base.size and a.tobytes() == b.tobytes() and a.tobytes() != photograph(base, 6).tobytes()
