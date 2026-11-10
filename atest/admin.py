"""Portal de configuração: usuários, sessões e versões da régua e dos checklists editadas pelo painel.

As edições não reescrevem os TOML de config/. Cada "Salvar" grava uma versão completa da seção no banco
(tabela config_versions); a configuração efetiva é a dos TOML com a última versão salva por cima. Assim:
- dá para ver quem mudou o quê e quando, e voltar a qualquer versão;
- "Restaurar padrão" grava uma versão vazia (volta ao que está nos TOML);
- a assinatura da configuração (gravada em cada parecer) muda junto, então dá para saber com qual regra cada parecer saiu.

Senhas: PBKDF2-SHA256 com sal aleatório. Sessões: token aleatório; no banco fica só o SHA-256 do token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import ValidationError

from .config import AdminSettings, Checklists, Settings
from .database import Database
from .domain import MAINTENANCE_PT, MOMENT_PT, SEVERITY_PT, Category, Rubric
from .formatting import pt_validation_error

Section = Literal["rubric", "checklists"]
SECTIONS: tuple[Section, ...] = ("rubric", "checklists")
PBKDF2_ITERATIONS = 390_000
USERNAME = re.compile(r"^[a-z0-9._-]{3,40}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT,
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES admin_users(username) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS config_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    section TEXT NOT NULL,
    data TEXT,
    author TEXT NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_config_versions_section ON config_versions(section, id);
"""


class AdminError(Exception):
    """Erro de regra do portal (credencial, bloqueio, validação), com status HTTP sugerido."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ============================================================================ senhas
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(calc, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def check_password_policy(password: str) -> None:
    if len(password) < 8:
        raise AdminError("A senha precisa ter pelo menos 8 caracteres.", 422)
    if password.isalpha() or password.isdigit():
        raise AdminError("Use letras e números (ou símbolos) na senha.", 422)


# ============================================================================ validação das seções
VALID_MAINTENANCE = {"*", "corrective", "preventive"}
VALID_MOMENT = {"*", "quote", "execution"}


def validate_section(section: Section, data: dict[str, Any], base: Settings) -> dict[str, Any]:
    """Valida a seção inteira (tipos pelo Pydantic + regras de negócio) e devolve a versão normalizada."""
    try:
        model = Rubric.model_validate(data) if section == "rubric" else Checklists.model_validate(data)
    except ValidationError as e:
        raise AdminError(f"Valor inválido: {pt_validation_error(e.errors())}", 422) from e

    if isinstance(model, Rubric):
        if sum(model.weights.values()) != 100:
            raise AdminError(f"Os pesos de escopo, orçamento e fotos precisam somar 100 (hoje somam {sum(model.weights.values())}).", 422)
        if any(w < 0 for w in model.weights.values()) or any(not 0 <= d <= 100 for d in model.discount_by_severity.values()):
            raise AdminError("Pesos não podem ser negativos e descontos ficam entre 0 e 100.", 422)
        mins = sorted(b.score_min for b in model.bands)
        if mins[0] != 0 or len(set(mins)) != len(mins) or any(not 0 <= m <= 100 for m in mins):
            raise AdminError("As faixas precisam começar em 0, ter mínimos diferentes e ficar entre 0 e 100.", 422)
        if set(model.finding_types) != set(base.rubric.finding_types):
            raise AdminError("Os tipos de apontamento são definidos no código: dá para ativar, desativar e ajustar, mas não criar ou apagar.", 422)
        for kind, spec in model.finding_types.items():
            for other in spec.absorbs:
                target = model.finding_types.get(other)
                if other == kind or target is None or target.validation != spec.validation:
                    name = f"“{target.description}”" if target else f"'{other}'"
                    msg = f"“{spec.description}” só pode absorver outro tipo existente da mesma validação ({name} não serve)."
                    raise AdminError(msg, 422)
        if model.confidence.medium_with_n_reducers > model.confidence.low_with_n_reducers:
            raise AdminError("A confiança média precisa de menos redutores do que a baixa.", 422)
        return model.model_dump(mode="json")

    categories = {c.value for c in Category} | {"*"}
    if set(model.attachment_categories) != set(base.checklists.attachment_categories):
        raise AdminError("As categorias de anexo são definidas no código: dá para ajustar a descrição, mas não criar ou apagar.", 422)
    seen: set[tuple[str, str, str]] = set()
    for n, rule in enumerate(model.rules, 1):
        where = f"regra {n} ({rule_label(rule.category, rule.maintenance, rule.moment)})"
        if rule.category not in categories:
            raise AdminError(f"{where}: categoria desconhecida.", 422)
        if rule.maintenance not in VALID_MAINTENANCE or rule.moment not in VALID_MOMENT:
            raise AdminError(f"{where}: tipo de manutenção ou etapa inválidos.", 422)
        key = (rule.category, rule.maintenance, rule.moment)
        if key in seen:
            raise AdminError(f"{where}: já existe outra regra para a mesma combinação.", 422)
        seen.add(key)
        if not rule.requirements:
            raise AdminError(f"{where}: precisa de pelo menos uma exigência (ou desative a regra).", 422)
        ids = [r.id for r in rule.requirements]
        if len(set(ids)) != len(ids):
            raise AdminError(f"{where}: há exigências com o mesmo identificador.", 422)
        for r in rule.requirements:
            if not re.fullmatch(r"[a-z0-9_]{2,40}", r.id):
                raise AdminError(f"{where}: identificador '{r.id}' inválido (use minúsculas, números e _).", 422)
            if not r.description.strip() or not r.accepted:
                raise AdminError(f"{where}: exigência '{r.id}' precisa de descrição e de pelo menos um tipo de anexo aceito.", 422)
    return model.model_dump(mode="json")


# ============================================================================ resumo das mudanças (histórico)
# Parâmetros numéricos da régua → nome em português (histórico do portal).
FIELD_PT = {
    "price_tolerance_pct": "Tolerância de preço (%)",
    "photo_date_tolerance_days": "Tolerância da data da foto (dias)",
    "spreadsheet_value_tolerance": "Tolerância de valor da planilha (R$)",
    "hash_max_distance": "Distância máxima de semelhança das fotos",
    "hash_max_distance_low_detail": "Distância máxima de semelhança (foto com pouco detalhe)",
    "hash_min_detail": "Detalhe mínimo da foto",
    "relevant_amount_at_issue_pct": "Valor divergente relevante (% do orçamento)",
}


def rule_label(category: str, maintenance: str, moment: str) -> str:
    """Regra do checklist em português: "Pintura / qualquer manutenção / atestação do serviço"."""
    try:
        cat = Category(category).label
    except ValueError:
        cat = "qualquer categoria" if category == "*" else category
    man = "qualquer manutenção" if maintenance == "*" else MAINTENANCE_PT.get(maintenance, maintenance)
    mom = "qualquer etapa" if moment == "*" else MOMENT_PT.get(moment, moment)
    return f"{cat} / {man} / {mom}"


def describe_changes(section: Section, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Frases curtas com o que mudou entre duas versões da seção, para o histórico."""
    out: list[str] = []
    if section == "rubric":
        for kind, a in after.get("finding_types", {}).items():
            b = before.get("finding_types", {}).get(kind, {})
            name = a.get("description", kind)
            if b.get("enabled", True) != a.get("enabled", True):
                out.append(f"{'Ativou' if a.get('enabled', True) else 'Desativou'} “{name}”")
            if b.get("severity") != a.get("severity"):
                out.append(f"“{name}”: severidade {SEVERITY_PT.get(b.get('severity'), b.get('severity'))} → {SEVERITY_PT.get(a['severity'], a['severity'])}")
            if b.get("phase") != a.get("phase"):
                out.append(f"“{name}”: fase {b.get('phase')} → {a.get('phase')}")
            for flag, label in (("lock", "trava"), ("reduces_confidence", "reduz confiança")):
                if bool(b.get(flag)) != bool(a.get(flag)):
                    out.append(f"“{name}”: {label} {'ligada' if a.get(flag) else 'desligada'}")
            if sorted(b.get("absorbs", [])) != sorted(a.get("absorbs", [])):
                types = after.get("finding_types", {})
                absorbed = [f"“{types.get(k, {}).get('description', k)}”" for k in a.get("absorbs", [])]
                out.append(f"“{name}”: absorve {', '.join(absorbed) or 'nenhum'}")
        for key, label in (("weights", "Pesos"), ("discount_by_severity", "Descontos por severidade"), ("bands", "Faixas"), ("confidence", "Confiança")):
            if before.get(key) != after.get(key):
                out.append(f"{label} alterados")
        for key, label in FIELD_PT.items():
            if before.get(key) != after.get(key):
                out.append(f"{label}: {before.get(key)} → {after.get(key)}")
    else:
        def key(r: dict) -> str:
            return rule_label(r["category"], r["maintenance"], r["moment"])

        rb = {key(r): r for r in before.get("rules", [])}
        ra = {key(r): r for r in after.get("rules", [])}
        for k in ra.keys() - rb.keys():
            out.append(f"Nova regra {k}")
        for k in rb.keys() - ra.keys():
            out.append(f"Removeu a regra {k}")
        for k in ra.keys() & rb.keys():
            a, b = ra[k], rb[k]
            if a.get("enabled", True) != b.get("enabled", True):
                out.append(f"{'Ativou' if a.get('enabled', True) else 'Desativou'} a regra {k}")
            qa = {q["id"]: q for q in a["requirements"]}
            qb = {q["id"]: q for q in b["requirements"]}
            for q in qa.keys() - qb.keys():
                out.append(f"{k}: nova exigência “{qa[q]['description']}”")
            for q in qb.keys() - qa.keys():
                out.append(f"{k}: removeu “{qb[q]['description']}”")
            for q in qa.keys() & qb.keys():
                if qa[q].get("enabled", True) != qb[q].get("enabled", True):
                    out.append(f"{k}: {'ativou' if qa[q].get('enabled', True) else 'desativou'} “{qa[q]['description']}”")
                elif qa[q] != qb[q]:
                    out.append(f"{k}: alterou “{qa[q]['description']}”")
        if before.get("attachment_categories") != after.get("attachment_categories"):
            out.append("Descrições das categorias de anexo alteradas")
    return out or ["Sem mudanças de conteúdo"]


# ============================================================================ armazenamento
class AdminStore:
    """Usuários, sessões e versões de configuração no mesmo banco do painel."""

    def __init__(self, database: Database, settings: AdminSettings):
        self.db = database
        self.settings = settings
        self._failures: dict[str, tuple[int, datetime]] = {}
        self._lock = threading.Lock()
        with self.db._transaction() as con:
            con.executescript(SCHEMA)
            for seed in settings.seed_users:
                con.execute(
                    "INSERT OR IGNORE INTO admin_users(username, password_hash, created_at, created_by) VALUES (?, ?, ?, 'config')",
                    (seed.username.lower(), seed.password_hash, datetime.now().isoformat(timespec="seconds")),
                )

    # ------------------------------------------------------------------ autenticação
    def login(self, username: str, password: str) -> tuple[str, datetime]:
        user = username.strip().lower()
        with self._lock:
            count, until = self._failures.get(user, (0, datetime.min))
            if until > datetime.now():
                minutes = max(1, round((until - datetime.now()).total_seconds() / 60))
                raise AdminError(f"Muitas tentativas. Tente de novo em {minutes} min.", 429)
        row = self.db._rows("SELECT password_hash FROM admin_users WHERE username = ?", (user,))
        if not row or not verify_password(password, row[0]["password_hash"]):
            with self._lock:
                count += 1
                lock = datetime.now() + timedelta(minutes=self.settings.lockout_minutes) if count >= self.settings.max_failed_logins else datetime.min
                self._failures[user] = (0 if lock > datetime.now() else count, lock)
            raise AdminError("Usuário ou senha incorretos.", 401)
        with self._lock:
            self._failures.pop(user, None)
        token = secrets.token_urlsafe(32)
        now = datetime.now()
        expires = now + timedelta(hours=self.settings.session_hours)
        with self.db._transaction() as con:
            con.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (now.isoformat(),))
            con.execute("INSERT INTO admin_sessions VALUES (?, ?, ?, ?)", (self._digest(token), user, now.isoformat(), expires.isoformat()))
            con.execute("UPDATE admin_users SET last_login = ? WHERE username = ?", (now.isoformat(timespec="seconds"), user))
        return token, expires

    def user_for(self, token: str | None) -> str | None:
        if not token:
            return None
        rows = self.db._rows("SELECT username, expires_at FROM admin_sessions WHERE token_hash = ?", (self._digest(token),))
        if not rows or datetime.fromisoformat(rows[0]["expires_at"]) < datetime.now():
            return None
        return rows[0]["username"]

    def logout(self, token: str) -> None:
        with self.db._transaction() as con:
            con.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (self._digest(token),))

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    # ------------------------------------------------------------------ usuários
    def users(self) -> list[dict[str, Any]]:
        return self.db._rows("SELECT username, created_at, created_by, last_login FROM admin_users ORDER BY username")

    def add_user(self, username: str, password: str, by: str) -> None:
        user = username.strip().lower()
        if not USERNAME.fullmatch(user):
            raise AdminError("Usuário: 3 a 40 caracteres, só minúsculas, números, ponto, hífen ou _.", 422)
        check_password_policy(password)
        if self.db._rows("SELECT 1 FROM admin_users WHERE username = ?", (user,)):
            raise AdminError("Esse usuário já existe.", 409)
        with self.db._transaction() as con:
            con.execute("INSERT INTO admin_users(username, password_hash, created_at, created_by) VALUES (?, ?, ?, ?)",
                        (user, hash_password(password), datetime.now().isoformat(timespec="seconds"), by))

    def change_password(self, username: str, current: str, new: str) -> None:
        row = self.db._rows("SELECT password_hash FROM admin_users WHERE username = ?", (username,))
        if not row or not verify_password(current, row[0]["password_hash"]):
            raise AdminError("A senha atual não confere.", 403)
        check_password_policy(new)
        if current == new:
            raise AdminError("A nova senha precisa ser diferente da atual.", 422)
        with self.db._transaction() as con:
            con.execute("UPDATE admin_users SET password_hash = ? WHERE username = ?", (hash_password(new), username))
            con.execute("DELETE FROM admin_sessions WHERE username = ?", (username,))  # derruba as outras sessões

    # ------------------------------------------------------------------ versões de configuração
    def latest(self, section: Section) -> dict[str, Any] | None:
        rows = self.db._rows("SELECT id, data FROM config_versions WHERE section = ? ORDER BY id DESC LIMIT 1", (section,))
        return {"id": rows[0]["id"], "data": json.loads(rows[0]["data"]) if rows[0]["data"] else None} if rows else None

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db._rows(
            "SELECT id, section, author, comment, summary, created_at, data IS NULL AS is_default FROM config_versions ORDER BY id DESC LIMIT ?", (limit,)
        )
        for r in rows:
            r["summary"] = json.loads(r["summary"])
            r["is_default"] = bool(r["is_default"])
        return rows

    def version(self, vid: int) -> dict[str, Any]:
        rows = self.db._rows("SELECT id, section, data FROM config_versions WHERE id = ?", (vid,))
        if not rows:
            raise AdminError("Versão não encontrada.", 404)
        return {"id": rows[0]["id"], "section": rows[0]["section"], "data": json.loads(rows[0]["data"]) if rows[0]["data"] else None}

    def save(self, section: Section, data: dict[str, Any] | None, base: Settings, author: str, comment: str) -> int:
        """Grava uma versão da seção (None = voltar ao padrão dos TOML) e devolve o id."""
        if not comment.strip():
            raise AdminError("Descreva o motivo da alteração: ele fica no histórico.", 422)
        before = self.section_data(section, base)
        normalized = validate_section(section, data, base) if data is not None else None
        after = normalized if normalized is not None else self.base_data(section, base)
        summary = describe_changes(section, before, after) if normalized is not None else ["Voltou ao padrão dos arquivos de configuração"]
        with self.db._transaction() as con:
            cur = con.execute(
                "INSERT INTO config_versions(section, data, author, comment, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (section, json.dumps(normalized, ensure_ascii=False) if normalized is not None else None, author, comment.strip()[:500],
                 json.dumps(summary, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
            )
            return int(cur.lastrowid)

    @staticmethod
    def base_data(section: Section, base: Settings) -> dict[str, Any]:
        return (base.rubric if section == "rubric" else base.checklists).model_dump(mode="json")

    def section_data(self, section: Section, base: Settings) -> dict[str, Any]:
        latest = self.latest(section)
        if not latest or latest["data"] is None:
            return self.base_data(section, base)
        data = dict(latest["data"])
        if section == "rubric":
            data["finding_types"] = self.merge_finding_types(base, data.get("finding_types", {}))
        return data

    @staticmethod
    def merge_finding_types(base: Settings, saved: dict[str, Any]) -> dict[str, Any]:
        """Tipos de apontamento da versão salva, completados pelo código.

        Os tipos são definidos no código: um tipo novo (ou um campo novo, como `absorbs`) que não existia quando a
        versão foi salva vem do TOML; um tipo que saiu do código é descartado.
        """
        out = {}
        for kind, spec in base.rubric.finding_types.items():
            out[kind] = {**spec.model_dump(mode="json"), **saved.get(kind, {})}
        return out

    def apply(self, base: Settings) -> Settings:
        """Configuração efetiva: os TOML com a última versão salva de cada seção por cima."""
        changes: dict[str, Any] = {}
        for section in SECTIONS:
            latest = self.latest(section)
            if latest and latest["data"] is not None:
                data = dict(latest["data"])
                if section == "rubric":  # a versão da régua mostra que veio do portal
                    data["version"] = f"{base.rubric.version}+portal.{latest['id']}"
                    data["finding_types"] = self.merge_finding_types(base, data.get("finding_types", {}))
                changes[section] = data
        return base.with_overrides(**changes) if changes else base


def apply_saved_config(cfg: Settings) -> Settings:
    """Atalho para a linha de comando: aplica as versões salvas no portal, se houver banco."""
    if not cfg.database_file.exists():
        return cfg
    return AdminStore(Database(cfg.database_file), cfg.admin).apply(cfg)
