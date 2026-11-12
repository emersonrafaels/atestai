import pytest

from atest.config import load_settings
from atest.repository import References, list_tickets


@pytest.fixture(scope="session")
def cfg(tmp_path_factory):
    """Configuração dos TOML, com saídas, banco, logs e cache em pasta temporária."""
    tmp = tmp_path_factory.mktemp("atest")
    return load_settings().with_overrides(
        **{
            "execution.mode": "simulated",
            "llm.use_disk_cache": False,
            "panel.simulated_delay_s": 0.0,
            "observability.log_console": False,
            "paths.output": tmp / "output",
            "paths.database": tmp / "atest.db",
            "paths.logs": tmp / "logs",
            "paths.cache": tmp / "cache",
            "batch.batch_collect_window_s": 0.3,
            "batch.batch_poll_interval_s": 0.05,
        }
    )


@pytest.fixture(scope="session")
def ref(cfg) -> References:
    return References(cfg)


@pytest.fixture(scope="session")
def demo(cfg) -> list[str]:
    """Os 13 casos do deck (números 00…, hoje no conjunto Cenários de teste); o de validação tem o próprio portão."""
    return [p.name for p in list_tickets(cfg.tickets_dir) if p.name.startswith("00")]
