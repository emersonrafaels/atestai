"""Custo de cada chamada ao modelo, em USD e BRL, a partir dos preços em config/settings.toml."""

from __future__ import annotations

import logging

from .config import CostSettings, Price, Settings

log = logging.getLogger(__name__)


class CostCalculator:
    """Converte tokens em custo (USD), aplica o desconto do batch e converte para BRL pela cotação configurada."""

    def __init__(self, cfg: Settings):
        self.settings: CostSettings = cfg.costs

    def price(self, model: str) -> Price | None:
        """Preço do modelo; aceita "provedor:modelo" ou só o id do modelo."""
        return self.settings.prices.get(model) or self.settings.prices.get(model.split(":", 1)[-1])

    def usd(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        via_batch: bool = False,
    ) -> float:
        """Custo de uma chamada. Sem preço configurado, registra 0 e avisa no log."""
        price = self.price(model)
        if price is None:
            log.warning("sem preço configurado para o modelo %s; custo registrado como 0", model)
            return 0.0
        # input_tokens da API já exclui os tokens lidos/gravados no cache
        total = (
            input_tokens * price.input + output_tokens * price.output + cache_read_tokens * price.cache_read + cache_write_tokens * price.cache_write
        ) / 1e6
        if via_batch:
            total *= 1 - self.settings.batch_discount
        return round(total, 6)

    def to_brl(self, usd: float) -> float:
        """Converte USD em BRL pela cotação de [costs]."""
        return round(usd * self.settings.usd_brl_rate, 4)
