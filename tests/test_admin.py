"""Portal de configuração: login, versões salvas por cima dos TOML e efeito das regras desativadas na análise."""

import copy
import time

import pytest
from fastapi.testclient import TestClient

from atest.admin import AdminError, AdminStore, hash_password, validate_section, verify_password
from atest.api import create_app
from atest.database import Database


@pytest.fixture()
def admin_cfg(cfg, tmp_path):
    """Banco próprio: as gravações do portal não vazam para os outros testes."""
    seed = [{"username": "tester", "password_hash": hash_password("senha-de-teste-1")}]
    return cfg.with_overrides(**{"paths.database": tmp_path / "admin.db", "admin.seed_users": seed})


def _login(c: TestClient) -> dict:
    r = c.post("/api/admin/login", json={"username": "tester", "password": "senha-de-teste-1"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _run(c: TestClient, ticket: str) -> dict:
    e = c.post("/api/runs", json={"tickets": [ticket], "mode": "simulated"}).json()
    for _ in range(1200):  # o 1º run indexa as fotos (hashes) e pode levar alguns segundos
        r = c.get(f"/api/runs/{e['id']}").json()
        if r["status"] == "completed":
            return r["tickets"][ticket]["assessment"]
        time.sleep(0.05)
    raise AssertionError("execução não terminou")


def test_password_hash_roundtrip():
    h = hash_password("abc12345")
    assert verify_password("abc12345", h) and not verify_password("abc12346", h) and "abc12345" not in h


def test_login_lockout_and_auth(admin_cfg):
    store = AdminStore(Database(admin_cfg.database_file), admin_cfg.admin)
    for _ in range(admin_cfg.admin.max_failed_logins):
        with pytest.raises(AdminError):
            store.login("tester", "errada")
    with pytest.raises(AdminError) as e:
        store.login("tester", "senha-de-teste-1")  # bloqueado mesmo com a senha certa
    assert e.value.status == 429

    c = TestClient(create_app(admin_cfg))
    assert c.get("/api/admin/overview").status_code == 401


def test_validation_rejects_bad_sections(admin_cfg):
    rub = admin_cfg.rubric.model_dump(mode="json")
    rub["weights"]["scope"] = 30
    with pytest.raises(AdminError, match="somar 100"):
        validate_section("rubric", rub, admin_cfg)
    chk = admin_cfg.checklists.model_dump(mode="json")
    chk["rules"].append(copy.deepcopy(chk["rules"][0]))
    with pytest.raises(AdminError, match="mesma combinação"):
        validate_section("checklists", chk, admin_cfg)


def test_disabled_rules_change_the_analysis_and_reset_restores(admin_cfg):
    c = TestClient(create_app(admin_cfg))
    h = _login(c)
    assert _run(c, "00517706")["recommendation"] == "return_locked"  # foto reaproveitada trava

    ov = c.get("/api/admin/overview", headers=h).json()
    rub = ov["sections"]["rubric"]["data"]
    rub["finding_types"]["reused_photo"]["enabled"] = False
    assert c.put("/api/admin/config/rubric", headers=h, json={"data": rub, "comment": "teste"}).status_code == 200
    after = _run(c, "00517706")
    assert "reused_photo" not in {f["kind"] for f in after["findings"]} and after["recommendation"] != "return_locked"
    assert "+portal." in c.get("/api/config").json()["rubric_version"]

    chk = ov["sections"]["checklists"]["data"]
    rule = next(r for r in chk["rules"] if r["category"] == "lighting" and r["moment"] == "execution")
    next(q for q in rule["requirements"] if q["id"] == "certificate")["enabled"] = False
    assert c.put("/api/admin/config/checklists", headers=h, json={"data": chk, "comment": "teste"}).status_code == 200
    assert "certificate" not in [q["id"] for q in _run(c, "00523310")["checklist"]["requirements"]]

    hist = c.get("/api/admin/history", headers=h).json()
    assert [x["section"] for x in hist] == ["checklists", "rubric"] and all(x["author"] == "tester" for x in hist)

    c.post("/api/admin/config/rubric/reset", headers=h, json={"comment": "volta"})
    assert _run(c, "00517706")["recommendation"] == "return_locked"
    assert c.get("/api/config").json()["rubric_version"] == admin_cfg.rubric.version
