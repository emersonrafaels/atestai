"""Atest.AI — ponto de entrada.

Toda a configuração está em config/*.toml (Dynaconf). Rode:  python main.py
- execution.action = "panel"    → sobe o painel web
- execution.action = "batch"    → roda os chamados (síncrono ou Message Batches) e grava as saídas
- execution.action = "validate" → roda o conjunto de validação e aplica o portão de qualidade (código de saída 1 se reprovar)
Trocar de ambiente: ATEST_ENV=production python main.py
"""

from __future__ import annotations

from atest.batch import BatchRunner
from atest.config import Action, Mode, Settings, load_settings, missing_keys
from atest.database import Database
from atest.domain import Assessment
from atest.observability import configure_logging
from atest.validation import DatasetCatalog


class Application:
    """Orquestração de alto nível: escolhe a ação configurada e a executa."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg

    def run(self) -> int:
        """Executa a ação de [execution.action] e devolve o código de saída do processo."""
        configure_logging(self.cfg)
        if self.cfg.execution.mode == Mode.API and (missing := missing_keys(self.cfg)):
            raise SystemExit(f"Modo API sem chave para: {', '.join(missing)}. Preencha config/.secrets.toml.")
        if self.cfg.execution.action == Action.PANEL:
            self.start_panel()
            return 0
        if self.cfg.execution.action == Action.VALIDATE:
            return 0 if self.validate() else 1
        self.run_batch()
        return 0

    def run_batch(self) -> None:
        """Lote: chamados → pipeline (checklist, escopo, orçamento, fotos, score, parecer) → banco e saídas."""
        cfg = self.cfg
        print(
            f"Atest.AI {cfg.version} · ambiente {cfg.environment} · modo {cfg.execution.mode.value} · lote {cfg.batch.kind.value} · "
            f"fase {cfg.pipeline.phase} · {cfg.models.main} + {cfg.models.fast}"
        )
        runner = BatchRunner(cfg, database=Database(cfg.database_file))
        result = runner.run(cfg.execution.tickets or None, on_complete=self._print_ticket)
        tokens_in, tokens_out = result.tokens
        print(
            f"\nExecução {result.run_id}: {len(result.assessments)} parecer(es), {len(result.errors)} erro(s), "
            f"{tokens_in:,} tokens de entrada, {tokens_out:,} de saída, custo US$ {result.cost_usd:,.4f} → {result.output_folder}"
        )
        if result.api_batches:
            print(f"Lotes enviados à Message Batches API: {', '.join(result.api_batches)}")
        if result.evaluation:
            print(result.evaluation.render())

    def validate(self) -> bool:
        """Portão de qualidade: roda o conjunto de validação e reprova a versão se as métricas ficarem abaixo dos limites.

        Use antes de publicar uma mudança de prompt, régua ou modelo (e no CI).
        """
        dataset = self.cfg.validation.dataset
        ids = DatasetCatalog(self.cfg).ids(dataset)
        print(f"Validação: conjunto '{dataset}' ({len(ids)} chamados) · assinatura da configuração {self.cfg.signature()}")
        result = BatchRunner(self.cfg, database=Database(self.cfg.database_file)).run(ids, label=f"validação · {dataset}")
        if result.validation is None:
            print("Sem gabarito para avaliar.")
            return False
        print(result.validation.render())
        return result.validation.gate_passed

    def start_panel(self) -> None:
        import uvicorn

        from atest.api import create_app

        print(f"Painel em http://localhost:{self.cfg.panel.port} (ambiente {self.cfg.environment})")
        uvicorn.run(create_app(self.cfg), host=self.cfg.panel.host, port=self.cfg.panel.port, log_level="warning")

    @staticmethod
    def _print_ticket(ticket_id: str, assessment: Assessment | None, error: str | None) -> None:
        if error or assessment is None:
            print(f"  {ticket_id}  ERRO {error}")
            return
        score = "—" if assessment.score is None else f"{assessment.score:>3}"
        print(
            f"  {ticket_id}  {assessment.workstream.value}  {assessment.category.label:<20} score {score}  "
            f"{assessment.recommendation.label:<34} R$ {assessment.cost_brl:,.4f}"
        )


def main() -> None:
    """Ponto de entrada: carrega a configuração e executa a ação configurada."""
    raise SystemExit(Application(load_settings()).run())


if __name__ == "__main__":
    main()
