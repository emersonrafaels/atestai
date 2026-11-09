"""Configuração do Atest.AI: Dynaconf lê os TOML de config/ e o Pydantic valida e tipa.

    config/settings.toml    execução, modelos, LLM, pipeline, lote, caminhos, painel, logs, custos
    config/rubric.toml       pesos, severidades, faixas, tolerâncias e tipos de apontamento
    config/checklists.toml  checklist mínimo por categoria (+ manutenção e momento)
    config/prompts.toml     prompts de sistema por tarefa (versionados)
    config/.secrets.toml    ANTHROPIC_API_KEY (fora do git)

Ambiente: ATEST_ENV=desenvolvimento|producao. Sobrescrita pontual: ATEST_<SECAO>__<CHAVE>=valor.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from dynaconf import Dynaconf, Validator
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .domain import AttachmentCategory, Rubric

ROOT = Path(__file__).resolve().parent.parent
DIR_CONFIG = ROOT / "config"


class Mode(StrEnum):
    """Modo de execução: chamadas reais ao provedor ou respostas simuladas pelo gabarito."""

    API = "api"
    SIMULATED = "simulated"


class BatchMode(StrEnum):
    """Envio síncrono (uma requisição por vez) ou pela Message Batches API."""

    SYNC = "sync"
    BATCH = "batch"


class Action(StrEnum):
    """O que `python main.py` faz."""

    PANEL = "panel"
    BATCH = "batch"
    VALIDATE = "validate"  # roda o conjunto de validação e aplica o portão de qualidade


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionSettings(_Section):
    """Seção [execution]: ação, modo e chamados da execução."""

    action: Action = Action.PANEL
    mode: Mode = Mode.SIMULATED
    tickets: list[str] = Field(default_factory=list)
    evaluate_against_ground_truth: bool = True


class ModelSettings(_Section):
    """Modelos no formato "provedor:modelo" (sem prefixo = llm.default_provider)."""

    main: str
    fast: str
    tasks: dict[str, str] = Field(default_factory=dict, description="Sobrescreve o modelo de uma tarefa específica")
    fallback: dict[str, str] = Field(default_factory=dict, description="Modelo usado se o principal/rápido falhar por erro transitório")


class LlmSettings(_Section):
    """Seção [llm]: parâmetros comuns às chamadas ao modelo."""

    default_provider: str = "anthropic"
    max_tokens: int = Field(8000, ge=256)
    effort: str = ""
    timeout_s: float = 180
    max_retries: int = Field(4, ge=0)
    image_max_side: int = 1568
    use_disk_cache: bool = True
    provider_options: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Opções extras por provedor, repassadas à sua fábrica (ex.: [llm.provider_options.iara])"
    )


class PipelineSettings(_Section):
    """Seção [pipeline]: fase da régua e paralelismo."""

    phase: int = Field(2, ge=1, le=2)
    parallel: int = Field(3, ge=1, le=32)


class BatchSettings(_Section):
    """Seção [batch]: modo de envio e tempos da Message Batches API."""

    kind: BatchMode = BatchMode.SYNC
    batch_collect_window_s: float = 2.0
    batch_poll_interval_s: float = 20
    batch_max_hours: float = 24


class Paths(_Section):
    """Seção [paths]: pastas de dados, saídas, cache, banco e logs (relativas à raiz do projeto)."""

    data: Path
    output: Path
    cache: Path
    database: Path
    logs: Path
    upload_id_prefix: str = "9"


class PanelProvider(_Section):
    """Provedor oferecido no seletor do painel, com os modelos que ele preenche ao ser escolhido."""

    label: str = ""
    main: str = Field(description='Modelo principal ("provedor:modelo" ou só o id do modelo)')
    fast: str = Field(description="Modelo rápido")
    enabled: bool = True


class PanelSettings(_Section):
    """Seção [panel]: endereço do painel web e provedores que aparecem no seletor."""

    host: str = "0.0.0.0"
    port: int = 8000
    simulated_delay_s: float = 0.45
    providers: dict[str, PanelProvider] = Field(default_factory=dict, description="Provedores do seletor do painel, na ordem do arquivo")

    @field_validator("providers")
    @classmethod
    def _models_belong_to_provider(cls, v: dict[str, PanelProvider]) -> dict[str, PanelProvider]:
        """Completa o prefixo "provedor:" dos modelos e recusa modelo de outro provedor (erro de digitação no TOML)."""
        out = {}
        for name, p in v.items():
            models = {}
            for role in ("main", "fast"):
                model = getattr(p, role)
                if ":" not in model:
                    model = f"{name}:{model}"
                elif model.split(":", 1)[0].strip().lower() != name:
                    raise ValueError(f"panel.providers.{name}.{role} = {model!r} é de outro provedor (use {name}:<modelo>)")
                models[role] = model
            out[name] = p.model_copy(update=models)
        return out


class AdminUserSeed(_Section):
    """Usuário criado no primeiro uso do portal (só o hash da senha fica no arquivo)."""

    username: str
    password_hash: str


class AdminSettings(_Section):
    """Seção [admin]: portal de configuração (usuários iniciais, duração da sessão, bloqueio por tentativas)."""

    session_hours: float = 8
    max_failed_logins: int = 5
    lockout_minutes: int = 5
    seed_users: list[AdminUserSeed] = Field(default_factory=list)


class ValidationResult(_Section):
    """Portão de qualidade: uma rodada no conjunto de validação abaixo destes limites reprova a versão."""

    dataset: str = "validation"
    accuracy_min: float = 0.85
    kappa_min: float = 0.75
    finding_f1_min: float = 0.80
    score_error_max: float = 8.0
    bootstrap_samples: int = 1000
    simulated_noise: float = 0.0


class ObservabilitySettings(_Section):
    """Seção [observability]: nível e destinos dos logs."""

    level: str = "INFO"
    log_json: bool = True
    log_console: bool = True


class Price(_Section):
    """Preço em USD por milhão de tokens."""

    input: float
    output: float
    cache_write: float
    cache_read: float


class CostSettings(_Section):
    """Seção [costs]: cotação, desconto do batch e preços por modelo."""

    usd_brl_rate: float = 5.40
    batch_discount: float = 0.5
    prices: dict[str, Price] = Field(default_factory=dict)


class ChecklistRequirement(_Section):
    """Um item obrigatório do checklist e as categorias de anexo que o atendem."""

    id: str
    description: str
    accepted: list[AttachmentCategory]
    enabled: bool = True


class ChecklistRule(_Section):
    """Regra de checklist para uma combinação categoria × manutenção × momento."""

    category: str = "*"
    maintenance: str = "*"
    moment: str = "*"
    requirements: list[ChecklistRequirement]
    enabled: bool = True

    def house(self, category: str, maintenance: str, moment: str) -> int | None:
        """Especificidade da regra (quanto maior, mais específica) ou None se não casa."""
        points = 0
        for rule_value, value in ((self.category, category), (self.maintenance, maintenance), (self.moment, moment)):
            if rule_value == "*":
                continue
            if rule_value != value:
                return None
            points += 1
        return points


class Checklists(_Section):
    """Checklists mínimos (config/checklists.toml)."""

    attachment_categories: dict[str, str]
    rules: list[ChecklistRule]

    def requirements(self, category: str, maintenance: str, moment: str) -> list[ChecklistRequirement]:
        """Requisitos ativos da regra ativa mais específica que casa com categoria, manutenção e momento."""
        rule = self.rule_for(category, maintenance, moment)
        return [r for r in rule.requirements if r.enabled] if rule else []

    def rule_for(self, category: str, maintenance: str, moment: str) -> ChecklistRule | None:
        """Regra ativa mais específica (em empate, a que vem por último no arquivo)."""
        candidates = [(r.house(category, maintenance, moment), i, r) for i, r in enumerate(self.rules) if r.enabled]
        valid = [(p, i, r) for p, i, r in candidates if p is not None]
        return max(valid, key=lambda x: (x[0], x[1]))[2] if valid else None


class Prompts(_Section):
    """Prompts de sistema por tarefa (config/prompts.toml, em português) e sua versão."""

    version: str
    identify_attachments: str
    scope: str
    quote_review: str
    photos: str
    assessment: str


class Settings(BaseModel):
    """Visão tipada e validada das configurações. Use `load_settings()` para obter."""

    model_config = ConfigDict(extra="ignore")

    environment: str = "development"
    version: str = "0.3.0"
    execution: ExecutionSettings
    models: ModelSettings
    llm: LlmSettings
    pipeline: PipelineSettings
    batch: BatchSettings
    paths: Paths
    panel: PanelSettings
    admin: AdminSettings = Field(default_factory=AdminSettings)
    observability: ObservabilitySettings
    validation: ValidationResult = Field(default_factory=ValidationResult)
    costs: CostSettings
    rubric: Rubric
    checklists: Checklists
    prompts: Prompts

    # atalhos de caminho (absolutos)
    def _abs(self, p: Path) -> Path:
        return p if p.is_absolute() else ROOT / p

    @property
    def data_dir(self) -> Path:
        return self._abs(self.paths.data)

    @property
    def tickets_dir(self) -> Path:
        return self.data_dir / "tickets"

    @property
    def history_dir(self) -> Path:
        return self.data_dir / "history"

    @property
    def references_dir(self) -> Path:
        return self.data_dir / "references"

    @property
    def ground_truth_dir(self) -> Path:
        return self.data_dir / "ground_truth"

    @property
    def output_dir(self) -> Path:
        return self._abs(self.paths.output)

    @property
    def cache_dir(self) -> Path:
        return self._abs(self.paths.cache)

    @property
    def database_file(self) -> Path:
        return self._abs(self.paths.database)

    @property
    def logs_dir(self) -> Path:
        return self._abs(self.paths.logs)

    def signature(self) -> str:
        """Impressão digital do que muda o resultado: régua, prompts, modelos, LLM e fase. Vai gravada em cada parecer."""
        import hashlib
        import json

        target = {
            "rubric": self.rubric.model_dump(mode="json"),
            "checklists": self.checklists.model_dump(mode="json"),
            "prompts": self.prompts.model_dump(),
            "models": self.models.model_dump(),
            "llm": self.llm.model_dump(include={"default_provider", "effort", "max_tokens", "image_max_side"}),
            "phase": self.pipeline.phase,
        }
        return hashlib.sha256(json.dumps(target, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]

    def with_overrides(self, **changes: Any) -> Settings:
        """Cópia com mudanças por caminho pontilhado, ex.: cfg.com(**{"execution.mode": "api", "pipeline.fase": 1})."""
        data = self.model_dump()
        for path, value in changes.items():
            target = data
            *country, key = path.split(".")
            for p in country:
                target = target[p]
            target[key] = value
        return Settings.model_validate(data)


VALIDATORS = [
    Validator("execution.mode", is_in=["api", "simulated"]),
    Validator("execution.action", is_in=["panel", "batch", "validate"]),
    Validator("batch.kind", is_in=["sync", "batch"]),
    Validator("pipeline.phase", is_in=[1, 2]),
    Validator("models.main", "models.fast", must_exist=True),
    Validator("rubric.weights", "rubric.bands", "prompts.version", must_exist=True),
]


def _lowercase(d: Any) -> Any:
    if isinstance(d, dict):
        return {str(k).lower(): _lowercase(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_lowercase(v) for v in d]
    return d


def build_dynaconf(environment: str | None = None) -> Dynaconf:
    """Carrega os TOML de config/ no ambiente pedido (ou em ATEST_ENV) com Dynaconf."""
    return Dynaconf(
        root_path=str(DIR_CONFIG),
        settings_files=["settings.toml", "rubric.toml", "checklists.toml", "prompts.toml"],
        secrets=".secrets.toml",
        environments=True,
        env_switcher="ATEST_ENV",
        env=environment or os.getenv("ATEST_ENV", "development"),
        envvar_prefix="ATEST",
        merge_enabled=True,
        validators=VALIDATORS,
    )


@lru_cache(maxsize=4)
def load_settings(environment: str | None = None) -> Settings:
    """Configuração validada (Pydantic) do ambiente; resultado em cache por processo."""
    settings = build_dynaconf(environment)
    for secret, variable in SECRETS.items():
        if (value := settings.get(secret)) and not os.getenv(variable):
            os.environ[variable] = value
    data = _lowercase(settings.as_dict())
    for secret in SECRETS:
        data.pop(secret, None)
    data["environment"] = settings.current_env.lower()
    return Settings.model_validate(data)


SECRETS = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "iara_client_id": "IARA_CLIENT_ID",
    "iara_client_secret": "IARA_CLIENT_SECRET",
    "iara_access_token": "IARA_ACCESS_TOKEN",
}
# variáveis de ambiente que um provedor precisa (todas) para funcionar
KEY_ENV_VAR: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "google": ("GEMINI_API_KEY",),
    "iara": ("IARA_CLIENT_ID", "IARA_CLIENT_SECRET"),
}


def has_credentials(provider: str) -> bool:
    """True se todas as variáveis de credencial do provedor estão no ambiente (provedor desconhecido: True)."""
    return all(os.getenv(v) for v in KEY_ENV_VAR.get(provider, ()))


def used_providers(cfg: Settings) -> set[str]:
    """Provedores de LLM citados em models (principal, rápido, tarefas e contingência)."""
    models = [cfg.models.main, cfg.models.fast, *cfg.models.tasks.values(), *cfg.models.fallback.values()]
    return {m.split(":", 1)[0].lower() if ":" in m else cfg.llm.default_provider for m in models if m}


def missing_keys(cfg: Settings) -> list[str]:
    """Provedores configurados sem credencial (chave de API ou client_id/secret) no ambiente."""
    return sorted(p for p in used_providers(cfg) if not has_credentials(p))


def api_available(cfg: Settings | None = None) -> bool:
    """True se há chave para todos os provedores que a configuração usa."""
    if cfg is None:
        return bool(os.getenv("ANTHROPIC_API_KEY"))
    return not missing_keys(cfg)
