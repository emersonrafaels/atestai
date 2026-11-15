"""Atest.AI — ponto de entrada.

Toda a configuração está em config/*.toml (Dynaconf). Rode:  python main.py
- execution.action = "panel"    → sobe o painel web
- execution.action = "batch"    → roda os chamados (síncrono ou Message Batches) e grava as saídas
- execution.action = "validate" → roda o conjunto de validação e aplica o portão de qualidade (código de saída 1 se reprovar)
Trocar de ambiente: ATEST_ENV=production python main.py
"""

from __future__ import annotations

from atest.batch import BatchRunner
from atest.admin import apply_saved_config
from atest.config import Action, Mode, Settings, load_settings, missing_keys
from atest.database import Database
from atest.domain import Assessment
from atest.observability import configure_logging
from atest.validation import DatasetCatalog


class Application:
    """Orquestração de alto nível: escolhe a ação configurada e a executa.

    Attributes:
        cfg: configuração validada (TOML + ajustes salvos no portal). Os campos que mais pesam aqui são
            `execution.action` (o que rodar), `execution.mode` (API ou simulado) e `batch.kind` (síncrono ou lote).
    """

    def __init__(self, cfg: Settings):
        """
        Args:
            cfg: configuração do ambiente, já carregada por `load_settings` (e, fora do painel, com `apply_saved_config`).
        """
        self.cfg = cfg

    def run(self) -> int:
        """Executa a ação de [execution.action] e devolve o código de saída do processo.

        Antes de qualquer ação, configura o log e, no modo API, confere se há credencial para todos os provedores
        citados em [models].

        Returns:
            0 em sucesso; 1 quando a ação é "validate" e o portão de qualidade reprova a versão.

        Raises:
            SystemExit: modo API sem chave para algum provedor configurado.
        """
        # Configura o log (terminal e arquivos em [paths.logs]) antes de qualquer outra coisa.
        configure_logging(self.cfg)

        # No modo API, todos os provedores citados em [models] precisam de credencial; no simulado não há chamada real.
        if self.cfg.execution.mode == Mode.API and (missing := missing_keys(self.cfg)):
            raise SystemExit(
                f"Modo API sem chave para: {', '.join(missing)}. Preencha config/.secrets.toml."
            )

        # Painel: sobe o servidor web e só volta quando o processo for encerrado.
        if self.cfg.execution.action == Action.PANEL:
            self.start_panel()
            return 0

        # Validação: o código de saída diz se a versão passou no portão de qualidade (útil no CI).
        if self.cfg.execution.action == Action.VALIDATE:
            return 0 if self.validate() else 1

        # Padrão ("batch"): roda os chamados e grava as saídas.
        self.run_batch()
        return 0

    def run_batch(self) -> None:
        """Lote: chamados → pipeline (checklist, escopo, orçamento, fotos, score, parecer) → banco e saídas.

        Roda os chamados de [execution.tickets] (vazio = todos da pasta de chamados), imprime uma linha por chamado
        ao terminar e, no fim, o resumo da execução: pareceres, erros, tokens, custo em US$, pasta de saída, lotes
        enviados à Message Batches API e a avaliação contra o gabarito (quando houver).

        Os argumentos passados ao BatchRunner:
            cfg: configuração do ambiente (modo, modelos, fase da régua, paralelismo).
            database: banco SQLite em [paths] onde a execução e os pareceres ficam gravados (o painel lê dele).

        Os argumentos passados ao BatchRunner.run:
            ids: [execution.tickets]; lista vazia vira None, que significa "todos os chamados".
            on_complete: `_print_ticket`, chamado ao fim de cada chamado para imprimir o resultado.
        """
        cfg = self.cfg

        # Cabeçalho: deixa claro em que versão, ambiente, modo e modelos a execução está rodando.
        print(
            f"Atest.AI {cfg.version} · ambiente {cfg.environment} · modo {cfg.execution.mode.value} · lote {cfg.batch.kind.value} · "
            f"fase {cfg.pipeline.phase} · {cfg.models.main} + {cfg.models.fast}"
        )
        # Monta o executor do lote (cliente de LLM, índice de fotos e orquestrador saem da configuração) e roda os chamados.
        runner = BatchRunner(cfg, database=Database(cfg.database_file))
        result = runner.run(
            cfg.execution.tickets or None, on_complete=self._print_ticket
        )

        # Resumo da execução: quantidade de pareceres e erros, tokens somados de todas as chamadas, custo e pasta de saída.
        tokens_in, tokens_out = result.tokens
        print(
            f"\nExecução {result.run_id}: {len(result.assessments)} parecer(es), {len(result.errors)} erro(s), "
            f"{tokens_in:,} tokens de entrada, {tokens_out:,} de saída, custo US$ {result.cost_usd:,.4f} → {result.output_folder}"
        )
        # Só no modo lote: ids dos lotes enviados, para conferir no console do provedor.
        if result.api_batches:
            print(
                f"Lotes enviados à Message Batches API: {', '.join(result.api_batches)}"
            )
        # Só quando há gabarito para os chamados: acertos por recomendação e por tipo de apontamento.
        if result.evaluation:
            print(result.evaluation.render())

    def validate(self) -> bool:
        """Portão de qualidade: roda o conjunto de validação e reprova a versão se as métricas ficarem abaixo dos limites.

        Use antes de publicar uma mudança de prompt, régua ou modelo (e no CI).

        Variáveis principais:
            dataset: nome do conjunto em [validation.dataset] ("all" para todos os chamados).
            ids: ids dos chamados desse conjunto, na ordem das pastas.

        Returns:
            True se o portão de qualidade aprovou; False se reprovou ou se nenhum chamado tinha gabarito.

        Os argumentos passados ao BatchRunner.run:
            ids: os chamados do conjunto de validação.
            label: rótulo gravado no banco, para a execução aparecer como validação no painel.
        """
        # Escolhe os chamados do conjunto configurado (ex.: "scenarios", "validation" ou "all").
        dataset = self.cfg.validation.dataset
        ids = DatasetCatalog(self.cfg).ids(dataset)

        # A assinatura identifica régua + prompts + modelos: permite comparar validações da mesma configuração.
        print(
            f"Validação: conjunto '{dataset}' ({len(ids)} chamados) · assinatura da configuração {self.cfg.signature()}"
        )

        # Roda como um lote comum; com gabarito, o BatchRunner já monta o relatório de validação.
        result = BatchRunner(self.cfg, database=Database(self.cfg.database_file)).run(
            ids, label=f"validação · {dataset}"
        )

        # Sem nenhum gabarito não há como medir a qualidade: a validação reprova.
        if result.validation is None:
            print("Sem gabarito para avaliar.")
            return False
        print(result.validation.render())
        return result.validation.gate_passed

    def start_panel(self) -> None:
        """Sobe o painel web (FastAPI + uvicorn) em [panel.host]:[panel.port] e bloqueia até o processo ser encerrado.

        Os argumentos passados ao uvicorn.run:
            app: aplicação FastAPI do painel (API em /api e front-end na raiz), criada por `create_app`.
            host: interface de rede em que o servidor escuta ([panel.host]; "0.0.0.0" abre para a rede).
            port: porta HTTP ([panel.port]).
            log_level: "warning" para o log de acesso do uvicorn não poluir o terminal (o log do Atest.AI segue igual).
        """
        # Importações locais: o lote e a validação não precisam carregar o servidor web.
        import uvicorn

        from atest.api import create_app

        print(
            f"Painel em http://localhost:{self.cfg.panel.port} (ambiente {self.cfg.environment})"
        )
        uvicorn.run(
            create_app(self.cfg),
            host=self.cfg.panel.host,
            port=self.cfg.panel.port,
            log_level="warning",
        )

    @staticmethod
    def _print_ticket(
        ticket_id: str, assessment: Assessment | None, error: str | None
    ) -> None:
        """Imprime uma linha por chamado concluído (callback `on_complete` do `BatchRunner`).

        Args:
            ticket_id: id do chamado.
            assessment: parecer gerado; None quando o chamado deu erro.
            error: mensagem do erro; None quando o chamado foi analisado.
        """
        # Chamado com erro: o lote segue, só registra a mensagem.
        if error or assessment is None:
            print(f"  {ticket_id}  ERRO {error}")
            return
        # Chamado devolvido no checklist não tem score: mostra "—".
        score = "—" if assessment.score is None else f"{assessment.score:>3}"
        print(
            f"  {ticket_id}  {assessment.workstream.value}  {assessment.category.label:<20} score {score}  "
            f"{assessment.recommendation.label:<34} R$ {assessment.cost_brl:,.4f}"
        )


def main() -> None:
    """Ponto de entrada: carrega a configuração (TOML + ajustes salvos no portal) e executa a ação configurada.

    No painel a configuração vai pura (o próprio painel aplica os ajustes do portal e precisa dos TOML como base
    para "Restaurar padrão"); no lote e na validação, os ajustes salvos já entram aqui.

    Raises:
        SystemExit: sempre, com o código de saída devolvido por `Application.run`.
    """
    # Lê os TOML de config/ do ambiente em ATEST_ENV (padrão "development") e valida.
    cfg = load_settings()
    # o painel aplica os ajustes do portal por conta própria (precisa dos TOML puros como base para "Restaurar padrão")
    raise SystemExit(
        Application(
            cfg if cfg.execution.action == Action.PANEL else apply_saved_config(cfg)
        ).run()
    )


if __name__ == "__main__":
    main()
