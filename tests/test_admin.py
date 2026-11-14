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


def test_absorbs_is_validated_and_old_saved_versions_get_new_types(admin_cfg):
    rub = admin_cfg.rubric.model_dump(mode="json")
    rub["finding_types"]["missing_after_photo"]["absorbs"] = ["out_of_scope_item"]  # outra validação
    with pytest.raises(AdminError, match="mesma validação"):
        validate_section("rubric", rub, admin_cfg)

    # versão salva antes de existir o tipo novo e o campo absorbs: os dois vêm do código
    saved = admin_cfg.rubric.model_dump(mode="json")
    del saved["finding_types"]["after_photo_unconfirmed_location"]
    del saved["finding_types"]["missing_after_photo"]["absorbs"]
    saved["finding_types"]["photo_mismatch"]["severity"] = "medium"
    merged = AdminStore.merge_finding_types(admin_cfg, saved["finding_types"])
    assert "after_photo_unconfirmed_location" in merged
    assert merged["missing_after_photo"]["absorbs"] == ["photo_mismatch"]
    assert merged["photo_mismatch"]["severity"] == "medium"  # o que foi salvo continua valendo


def test_clear_analysis_history_selected_and_all(admin_cfg):
    c = TestClient(create_app(admin_cfg))
    assert c.get("/api/admin/assessments").status_code == 401
    h = _login(c)
    first = _run(c, "00517706")
    second = _run(c, "00523310")
    c.post(f"/api/assessments/{first['record_id']}/feedback", json={"action": "accept"})
    assert c.post(f"/api/assessments/{first['record_id']}/findings/0/feedback", json={"verdict": "correct"}).status_code == 201
    listed = c.get("/api/admin/assessments", headers=h).json()
    assert {a["id"] for a in listed} == {first["record_id"], second["record_id"]}
    assert next(a for a in listed if a["id"] == first["record_id"])["feedbacks"] == 1

    assert c.post("/api/admin/assessments/delete", json={}, headers=h).status_code == 422
    r = c.post("/api/admin/assessments/delete", json={"ids": [first["record_id"]]}, headers=h).json()
    assert r["assessments"] == 1 and r["feedbacks"] == 1 and r["runs_removed"] == [first["run_id"]]
    assert [a["id"] for a in c.get("/api/admin/assessments", headers=h).json()] == [second["record_id"]]
    assert c.get(f"/api/assessments/{first['record_id']}").status_code == 404
    assert c.get(f"/api/runs/{first['run_id']}").status_code == 404  # execução vazia saiu (também da memória)
    assert c.get("/api/tickets/00517706/history").json() == []

    r = c.post("/api/admin/assessments/delete", json={"all": True}, headers=h).json()
    assert r["assessments"] == 1
    assert c.get("/api/admin/assessments", headers=h).json() == []
    m = c.get("/api/metrics").json()
    assert m["assessments"] == 0 and m["runs"] == 0


def test_catalog_crud_and_rules(admin_cfg):
    """Cadastro: incluir categoria (com esteira) e sintoma ligado; não apagar o que está em uso; checklist com esteira."""
    c = TestClient(create_app(admin_cfg))
    h = _login(c)
    ov = c.get("/api/admin/overview", headers=h).json()
    cat = copy.deepcopy(ov["sections"]["catalog"]["data"])
    cat["categories"].append({"value": "glazing", "label": "Vidraçaria", "enabled": True, "workstreams": ["SETA"], "categories": []})
    cat["symptoms"].append({"value": "cracked_glass", "label": "Vidro trincado", "enabled": True, "workstreams": [], "categories": ["glazing"]})
    cat["locations"].append({"value": "sala_de_reuniao", "label": "Sala de reunião", "enabled": True, "workstreams": [], "categories": []})
    r = c.put("/api/admin/config/catalog", json={"data": cat, "comment": "nova categoria"}, headers=h)
    assert r.status_code == 200, r.text
    conf = c.get("/api/config").json()
    assert {"value": "glazing", "label": "Vidraçaria"}.items() <= next(x for x in conf["categories"] if x["value"] == "glazing").items()
    assert any(x["value"] == "sala_de_reuniao" for x in conf["locations"])
    assert "Novo categoria: “Vidraçaria”" in c.get("/api/admin/history", headers=h).json()[0]["summary"]

    # checklist próprio da categoria nova, só na SETA
    chk = copy.deepcopy(r.json()["sections"]["checklists"]["data"])
    chk["rules"].append({"workstream": "SETA", "category": "glazing", "maintenance": "*", "moment": "execution", "enabled": True,
                         "requirements": [{"id": "quote", "description": "Orçamento", "accepted": ["quote_doc"], "enabled": True}]})
    assert c.put("/api/admin/config/checklists", json={"data": chk, "comment": "vidros"}, headers=h).status_code == 200
    dup = copy.deepcopy(chk)
    dup["rules"].append(copy.deepcopy(chk["rules"][-1]))
    assert c.put("/api/admin/config/checklists", json={"data": dup, "comment": "x"}, headers=h).status_code == 422

    # apagar em uso (chamados, regra de checklist) é recusado; sintoma ligado a categoria inexistente também
    used = copy.deepcopy(cat)
    used["categories"] = [x for x in used["categories"] if x["value"] not in ("plumbing", "glazing")]
    used["symptoms"] = [{**s, "categories": [k for k in s["categories"] if k not in ("plumbing", "glazing")]} for s in used["symptoms"]]
    r = c.put("/api/admin/config/catalog", json={"data": used, "comment": "x"}, headers=h)
    assert r.status_code == 409 and "Desative" in r.json()["detail"]
    bad = copy.deepcopy(cat)
    bad["symptoms"][-1]["categories"] = ["nao_existe"]
    assert c.put("/api/admin/config/catalog", json={"data": bad, "comment": "x"}, headers=h).status_code == 422
    # sem uso pode apagar
    free = copy.deepcopy(cat)
    free["locations"] = [x for x in free["locations"] if x["value"] != "sala_de_reuniao"]
    assert c.put("/api/admin/config/catalog", json={"data": free, "comment": "x"}, headers=h).status_code == 200

    # envio de chamado confere o cadastro: categoria fora da esteira e sintoma de outra categoria são recusados
    form = {"workstream": "SISR", "category": "glazing", "symptom": "cracked_glass", "maintenance_type": "corrective",
            "moment": "execution", "scope": "Trocar vidro", "branch_name": "Ag. Teste"}
    sheet = next((admin_cfg.tickets_dir / "00534519" / "attachments").glob("*.xlsx")).read_bytes()
    r = c.post("/api/tickets", data=form, files=[("spreadsheet", ("q.xlsx", sheet))])
    assert r.status_code == 422 and "esteira" in r.json()["detail"]
    r = c.post("/api/tickets", data={**form, "workstream": "SETA", "symptom": "leak"}, files=[("spreadsheet", ("q.xlsx", sheet))])
    assert r.status_code == 422 and "não vale" in r.json()["detail"]


def test_location_by_workstream_and_blocks_opening(admin_cfg):
    """Local da outra esteira é recusado no envio; 'impede a abertura' vai para o chamado e para o resumo do modelo."""
    c = TestClient(create_app(admin_cfg))
    sheet = next((admin_cfg.tickets_dir / "00534519" / "attachments").glob("*.xlsx")).read_bytes()
    form = {"workstream": "SETA", "category": "plumbing", "symptom": "leak", "maintenance_type": "corrective", "moment": "execution",
            "scope": "Vazamento na copa", "branch_name": "Ag. Teste", "environment": "sala_de_seguranca"}
    r = c.post("/api/tickets", data=form, files=[("spreadsheet", ("q.xlsx", sheet))])
    assert r.status_code == 422 and "esteira" in r.json()["detail"]
    ok = {**form, "environment": "area_interna_backoffice", "blocks_opening": "true", "solution_description": "Trocar a mangueira do dreno"}
    r = c.post("/api/tickets", data=ok, files=[("spreadsheet", ("q.xlsx", sheet))])
    assert r.status_code == 201, r.text
    tid = r.json()["ticket_id"]
    try:
        assert r.json()["blocks_opening"] is True and r.json()["solution_description"] == "Trocar a mangueira do dreno"
        from atest.repository import load_ticket

        text = load_ticket(admin_cfg.tickets_dir / tid).data.summary_text()
        assert "Impede a abertura da agência: sim" in text and "Área interna - backoffice" in text
        assert "DESCRIÇÃO DA SOLUÇÃO (informada no chamado): Trocar a mangueira do dreno" in text
    finally:
        assert c.delete(f"/api/tickets/{tid}").status_code == 204


def test_saved_catalog_gets_new_default_items(admin_cfg):
    """Versão salva do cadastro + item novo no arquivo: o novo aparece; o que o portal apagou continua fora."""
    store = AdminStore(Database(admin_cfg.database_file), admin_cfg.admin)
    data = admin_cfg.catalog.model_dump(mode="json")
    data["locations"] = [e for e in data["locations"] if e["value"] != "todas"]  # sem uso: pode apagar
    store.save("catalog", data, admin_cfg, "tester", "tira 'Todas'")
    newer = admin_cfg.catalog.model_dump(mode="json")
    newer["categories"].append({"value": "vidracaria", "label": "Vidraçaria", "enabled": True, "workstreams": ["SETA"], "categories": []})
    base2 = admin_cfg.with_overrides(**{"catalog": newer})  # o arquivo ganhou uma categoria depois da versão salva
    eff = store.apply(base2).catalog
    assert "vidracaria" in eff.codes("categories")
    assert "todas" not in eff.codes("locations")
    assert "vidracaria" in [e["value"] for e in store.section_data("catalog", base2)["categories"]]


def test_upload_with_items_only_and_items_template(admin_cfg, tmp_path):
    """Novo chamado: o modelo tem só a aba Itens e a planilha enviada pode ter só os itens."""
    import io

    from openpyxl import Workbook, load_workbook

    c = TestClient(create_app(admin_cfg))
    model = load_workbook(io.BytesIO(c.get("/api/spreadsheet-template").content))
    assert model.sheetnames == ["Itens"]  # os dados do chamado vêm do formulário
    assert [c.value for c in model["Itens"][1]] == ["Descrição", "Unidade", "LPU", "Quantidade", "Valor unitário"]  # o total é calculado

    wb = Workbook()
    wb.active.append(["Descrição", "Unidade", "Quantidade", "Valor unitário"])  # sem valor total nem linha de total
    wb.active.append(["Troca do sifão", "un", 2, 42.5])
    buf = io.BytesIO()
    wb.save(buf)
    form = {"workstream": "SETA", "category": "plumbing", "symptom": "leak", "maintenance_type": "corrective", "moment": "quote",
            "scope": "Vazamento na copa", "branch_name": "Ag. Centro", "supplier_name": "Hidro Ltda"}
    r = c.post("/api/tickets", data=form, files=[("spreadsheet", ("itens.xlsx", buf.getvalue()))])
    assert r.status_code == 201, r.text
    tid = r.json()["ticket_id"]
    try:
        assert r.json()["quoted_value"] == 85.0 and r.json()["supplier"] == "Hidro Ltda"
        detail = c.get(f"/api/tickets/{tid}").json()
        assert detail["quote_error"] is None and detail["quote"]["ticket_id"] == tid and detail["quote"]["scope"] == "Vazamento na copa"
    finally:
        assert c.delete(f"/api/tickets/{tid}").status_code == 204
