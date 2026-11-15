"""Camada de LLM do Atest.AI, independente de provedor.

- `ProviderClient`: síncrono. Resolve "provedor:modelo" (Anthropic, OpenAI, Google...), aplica cache em disco,
  contingência (fallback) em erro transitório e devolve o rastro da chamada.
- `BatchClient`: Message Batches (ou equivalente). Os pipelines de todos os chamados rodam em paralelo; cada
  chamada entra numa fila e, quando todos os pipelines ativos estão esperando, a fila vira UM lote por provedor.
  Provedores sem lote nativo seguem no modo síncrono.
- `SimulatedClient` (simulated.py): responde pelo gabarito.
- `LlmSession`: o que as etapas usam; escolhe o modelo por tarefa, calcula custo, registra rastro e log.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from . import providers
from .config import Settings
from .costs import CostCalculator
from .domain import LlmCall
from .formatting import plain_language
from .observability import event, waiting
from .providers import Part, Provider, ProviderError, ProviderResponse, Request

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

# teto da nova tentativa quando a resposta é cortada no limite de tokens de saída
MAX_OUTPUT_TOKENS = 16000
LlmError = ProviderError


class LlmTimeout(ProviderError):
    """O modelo não respondeu dentro do limite calculado para a chamada (API fora do ar ou travada)."""


def call_timeout(
    cfg: Settings, images: int = 0, documents: int = 0, max_tokens: int = 4000
) -> float:
    """Limite de cada tentativa, pelo tamanho do pedido: muitas fotos ou PDFs e respostas longas ganham mais tempo.

    Fórmula: base + imagens × s/imagem + documentos × s/documento + (max_tokens / 1000) × s/1k tokens, limitada
    entre [llm.timeout_min_s] e [llm.timeout_max_s].

    Args:
        cfg: configuração (os coeficientes vêm de [llm]).
        images: quantidade de imagens no pedido.
        documents: quantidade de PDFs no pedido.
        max_tokens: limite de tokens de saída do pedido.

    Returns:
        Tempo limite em segundos, arredondado a uma casa.
    """
    llm = cfg.llm
    # Tempo base + tempo extra por imagem e por PDF enviados (o modelo leva mais para "ler" cada anexo).
    t = (
        llm.timeout_base_s
        + images * llm.timeout_per_image_s
        + documents * llm.timeout_per_document_s
    )
    # Respostas longas também demoram mais para serem geradas.
    t += max_tokens / 1000 * llm.timeout_per_1k_tokens_s
    # Limita entre o mínimo e o máximo configurados.
    return round(min(max(t, llm.timeout_min_s), llm.timeout_max_s), 1)


def run_with_deadline(fn: Any, deadline_s: float, what: str) -> Any:
    """Roda `fn` numa thread e desiste em `deadline_s`: a análise não fica presa se a API travar sem responder.

    A thread presa segue até o tempo limite do próprio SDK (é daemon e não segura o processo).

    Args:
        fn: função sem argumentos a executar (roda com uma cópia do contextvars atual, para manter o contexto do log).
        deadline_s: tempo máximo de espera, em segundos.
        what: descrição de quem está sendo esperado, usada na mensagem de erro.

    Returns:
        O que `fn` devolver.

    Raises:
        LlmTimeout: `fn` não terminou dentro de `deadline_s` (marcado como transitório).
        Exception: qualquer erro levantado por `fn` é repassado a quem chamou.
    """
    import contextvars

    # `box` leva o resultado (ou o erro) da thread de volta para quem chamou.
    box: dict[str, Any] = {}
    # Copia o contexto atual (id da execução e do chamado no log) para dentro da thread.
    ctx = contextvars.copy_context()

    def target() -> None:
        try:
            box["value"] = ctx.run(fn)
        except BaseException as e:  # noqa: BLE001 — repassado a quem chamou
            box["error"] = e

    # Thread daemon: se a chamada travar, ela não impede o processo de terminar.
    thread = threading.Thread(target=target, daemon=True, name="atest-llm-call")
    thread.start()
    # Espera no máximo `deadline_s`; se a thread ainda estiver viva, a API travou.
    thread.join(deadline_s)
    if thread.is_alive():
        raise LlmTimeout(
            f"{what} não respondeu em {deadline_s:.0f} s; a API do modelo pode estar fora do ar ou travada",
            transient=True,
        )
    if "error" in box:
        raise box["error"]
    return box["value"]


def short_hash(text: str) -> str:
    """Hash curto (12 caracteres) de um texto, para versionar prompts e esquemas."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


class LlmClient(Protocol):
    """Contrato dos clientes de LLM usados pelo pipeline (provedores, lote ou simulado)."""

    simulated: bool
    via_batch: bool

    def structured(
        self,
        *,
        task: str,
        system: str,
        parts: list[Part],
        output: type[T],
        model: str,
        max_tokens: int,
        meta: dict[str, Any],
        fallback: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[T, LlmCall]:
        """Faz uma chamada com saída estruturada e devolve o objeto validado e o registro da chamada.

        Args:
            task: nome da tarefa (ex.: "scope", "photos"), usado no cache, no log e na escolha do prompt.
            system: prompt de sistema.
            parts: conteúdo do pedido (texto, imagens e PDFs).
            output: modelo Pydantic esperado na resposta.
            model: "provedor:modelo" (sem prefixo, vale [llm.default_provider]).
            max_tokens: limite de tokens de saída.
            meta: dados extras de rastreio (ex.: id do chamado, anexos enviados).
            fallback: modelo de contingência, usado em erro transitório; None desliga.
            timeout_s: limite de cada tentativa no provedor; None usa o padrão do SDK.

        Returns:
            (objeto validado do tipo `output`, registro da chamada com tokens, tempo, modelo e hashes).
        """
        ...


# --------------------------------------------------------------------------- síncrono, multi-provedor
class ProviderClient:
    """Cliente síncrono: roteia para o provedor do modelo, usa cache em disco e contingência."""

    simulated = False
    via_batch = False

    def __init__(self, cfg: Settings, instances: dict[str, Provider] | None = None):
        self.cfg = cfg
        self._instances = instances or {}
        if cfg.llm.use_disk_cache:
            cfg.cache_dir.mkdir(parents=True, exist_ok=True)

    def provider(self, name: str) -> Provider:
        """Instância do provedor pelo nome (injetada nos testes ou criada pelo registro).

        Os argumentos passados ao providers.get:
            timeout_s: tempo limite padrão do SDK ([llm.timeout_s]).
            max_retries: novas tentativas do próprio SDK em erro de rede/limite de taxa ([llm.max_retries]).
            **options: opções específicas do provedor ([llm.provider_options.<nome>], ex.: região, endpoint).
        """
        # Instâncias injetadas (testes) têm prioridade sobre o registro global.
        if name in self._instances:
            return self._instances[name]
        options = self.cfg.llm.provider_options.get(name, {})
        return providers.get(
            name,
            timeout_s=self.cfg.llm.timeout_s,
            max_retries=self.cfg.llm.max_retries,
            **options,
        )

    def _request(
        self, task: str, system: str, parts: list[Part], model: str, max_tokens: int
    ) -> tuple[str, Request]:
        """Separa "provedor:modelo" e monta a requisição neutra (com o esforço de raciocínio de [llm.effort])."""
        prov, mid = providers.split_model(model, self.cfg.llm.default_provider)
        return prov, Request(
            task=task,
            system=system,
            parts=parts,
            model=mid,
            max_tokens=max_tokens,
            effort=self.cfg.llm.effort,
        )

    # ------------------------------------------------------------------ cache em disco
    def _file(self, prov: str, req: Request, output: type[BaseModel]):
        """Arquivo de cache da requisição: tarefa + provedor + hash de (modelo, prompt, conteúdo, schema)."""
        return (
            self.cfg.cache_dir / f"{req.task}_{prov}_{req.key(output, prov)[:24]}.json"
        )

    def _from_cache(
        self, prov: str, req: Request, output: type[T]
    ) -> tuple[T, LlmCall] | None:
        """Resposta guardada em disco para a mesma requisição, ou None (cache desligado, em renovação ou sem arquivo).

        A chamada vinda do cache é registrada com `from_cache=True`, sem tokens e sem custo.
        """
        # Cache desligado, ou pedido para renovar (refresh_cache): sempre vai ao provedor.
        if not self.cfg.llm.use_disk_cache or self.cfg.llm.refresh_cache:
            return None
        file = self._file(prov, req, output)
        if not file.exists():
            return None
        # Valida de novo contra o schema atual: um cache incompatível falha aqui em vez de seguir com dado errado.
        data = json.loads(file.read_text(encoding="utf-8"))
        obj = output.model_validate(data["response"])
        return obj, self._call(
            prov,
            req,
            output,
            obj,
            None,
            0.0,
            datetime.now(),
            resolved_model=data.get("resolved_model", ""),
            from_cache=True,
        )

    def _store(
        self, prov: str, req: Request, output: type[BaseModel], resp: ProviderResponse
    ) -> None:
        """Grava a resposta (e o id efetivo do modelo) no cache em disco, se o cache estiver ligado."""
        if self.cfg.llm.use_disk_cache:
            content = {
                "resolved_model": resp.resolved_model,
                "response": resp.obj.model_dump(mode="json"),
            }
            self._file(prov, req, output).write_text(
                json.dumps(content, ensure_ascii=False), encoding="utf-8"
            )

    def _call(
        self,
        prov: str,
        req: Request,
        output: type[BaseModel],
        obj: BaseModel,
        resp: ProviderResponse | None,
        dur: float,
        start: datetime,
        resolved_model: str = "",
        from_cache: bool = False,
    ) -> LlmCall:
        """Registro (rastro) de uma chamada, que vai para o parecer e para o banco.

        Args:
            prov: nome do provedor.
            req: requisição enviada.
            output: modelo Pydantic da resposta (o hash do schema entra no registro).
            obj: resposta validada.
            resp: resposta do provedor; None quando veio do cache.
            dur: duração da chamada, em segundos.
            start: início da chamada.
            resolved_model: id efetivo do modelo quando a resposta veio do cache.
            from_cache: True se a resposta veio do cache em disco.

        Returns:
            O `LlmCall`, com tokens, modelo pedido e efetivo, lote, versão e hash do prompt e hash do schema.
            O custo é preenchido depois, por `LlmSession`.
        """
        # Resposta do cache não consumiu tokens: uso zerado.
        u = resp.usage if resp else providers.Usage()
        return LlmCall(
            task=req.task,
            provider=prov,
            model=f"{prov}:{req.model}",
            resolved_model=resp.resolved_model if resp else resolved_model,
            start=start,
            duration_s=round(dur, 2),
            input_tokens=u.input,
            output_tokens=u.output,
            cache_read_tokens=u.cache_read_tokens,
            cache_write_tokens=u.cache_write_tokens,
            from_cache=from_cache,
            via_batch=bool(resp and resp.via_batch),
            batch_id=resp.batch_id if resp else None,
            prompt_version=self.cfg.prompts.version,
            prompt_hash=short_hash(req.system),
            schema_hash=short_hash(
                json.dumps(output.model_json_schema(), sort_keys=True)
            ),
            response=obj.model_dump(mode="json"),
        )

    # ------------------------------------------------------------------ chamada
    def structured(
        self,
        *,
        task: str,
        system: str,
        parts: list[Part],
        output: type[T],
        model: str,
        max_tokens: int,
        meta: dict[str, Any],
        fallback: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[T, LlmCall]:
        """Faz uma chamada com saída estruturada e devolve o objeto validado e o registro da chamada.

        Ordem: cache em disco (se [llm.use_disk_cache] e não [llm.refresh_cache]) → provedor do modelo → em erro
        transitório, uma nova chamada com o modelo de `fallback`. A resposta válida é gravada no cache.
        Os argumentos são os de `LlmClient.structured`.

        Returns:
            (objeto validado do tipo `output`, registro da chamada).

        Raises:
            ProviderError: erro do provedor que não é transitório, ou sem modelo de contingência.
        """
        prov, req = self._request(task, system, parts, model, max_tokens)
        req.timeout_s = timeout_s
        # 1. Mesma requisição já respondida antes: devolve do cache, sem custo.
        if (hit := self._from_cache(prov, req, output)) is not None:
            return hit
        # 2. Chama o provedor do modelo, medindo o tempo.
        start, t0 = datetime.now(), time.perf_counter()
        try:
            resp = self.provider(prov).generate(req, output)
        except ProviderError as e:
            # 3. Erro transitório (fora do ar, sobrecarga, tempo esgotado) com contingência configurada: tenta o outro modelo.
            #    Erro permanente (ex.: pedido inválido) ou sem contingência: repassa o erro.
            if not (e.transient and fallback and fallback != model):
                raise
            event(
                "llm_fallback",
                logging.WARNING,
                task=task,
                model=model,
                fallback=fallback,
                error=str(e),
            )
            return self.structured(
                task=task,
                system=system,
                parts=parts,
                output=output,
                model=fallback,
                max_tokens=max_tokens,
                meta=meta,
                timeout_s=timeout_s,
            )
        # 4. Resposta válida: guarda no cache e devolve com o registro da chamada.
        self._store(prov, req, output, resp)
        return resp.obj, self._call(
            prov, req, output, resp.obj, resp, time.perf_counter() - t0, start
        )


# --------------------------------------------------------------------------- lote (Message Batches e equivalentes)
@dataclass
class _Pending:
    custom_id: str
    provider: str
    req: Request
    output: type[BaseModel]
    created: float = field(default_factory=time.monotonic)
    ready: threading.Event = field(default_factory=threading.Event)
    obj: BaseModel | None = None
    call: LlmCall | None = None
    error: Exception | None = None


class BatchClient(ProviderClient):
    """Cliente que junta as chamadas de vários pipelines e envia cada rodada como um lote assíncrono."""

    via_batch = True

    def __init__(self, cfg: Settings, instances: dict[str, Provider] | None = None):
        """
        Args:
            cfg: configuração ([batch] define janela de coleta, intervalo de consulta e prazo máximo do lote).
            instances: provedores já instanciados (testes); None usa o registro de provedores.
        """
        super().__init__(cfg, instances)
        # Trava + sinal compartilhados entre os pipelines (que enfileiram) e o coordenador (que envia os lotes).
        self._cond = threading.Condition()
        # Chamadas esperando o próximo lote.
        self._pending: list[_Pending] = []
        # Pipelines (chamados) em andamento; a rodada fecha quando todos estão esperando resposta.
        self._active = 0
        self._stop = False
        # Ids de todos os lotes enviados nesta execução.
        self.batches: list[str] = []
        # Thread coordenadora: fica de fundo decidindo quando enviar cada lote.
        threading.Thread(
            target=self._coordinate, name="coordenador-lote", daemon=True
        ).start()

    def register_pipeline(self) -> None:
        """Avisa que um pipeline começou (o coordenador espera todos antes de fechar uma rodada)."""
        with self._cond:
            self._active += 1

    def close_pipeline(self) -> None:
        """Avisa que um pipeline terminou."""
        with self._cond:
            self._active -= 1
            self._cond.notify_all()

    def close(self) -> None:
        """Encerra o coordenador de lotes."""
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def structured(
        self,
        *,
        task: str,
        system: str,
        parts: list[Part],
        output: type[T],
        model: str,
        max_tokens: int,
        meta: dict[str, Any],
        fallback: str | None = None,
        timeout_s: float | None = None,
    ) -> tuple[T, LlmCall]:
        """Enfileira a chamada no próximo lote e bloqueia a thread do pipeline até o resultado chegar.

        Cache em disco e provedores sem lote nativo seguem como no `ProviderClient`. Os argumentos são os de
        `LlmClient.structured`; `meta["ticket"]` entra no `custom_id` da requisição no lote.

        Returns:
            (objeto validado do tipo `output`, registro da chamada).

        Raises:
            ProviderError: a requisição falhou no lote, ficou sem resultado ou o lote passou de [batch.batch_max_hours].
        """
        prov, req = self._request(task, system, parts, model, max_tokens)
        req.timeout_s = timeout_s
        if (hit := self._from_cache(prov, req, output)) is not None:
            return hit
        if not self.provider(prov).supports_batch:  # sem lote nativo: segue síncrono
            return super().structured(
                task=task,
                system=system,
                parts=parts,
                output=output,
                model=model,
                max_tokens=max_tokens,
                meta=meta,
                fallback=fallback,
                timeout_s=timeout_s,
            )
        # custom_id único no lote: chamado + tarefa + sufixo aleatório (o mesmo chamado pode repetir a tarefa).
        p = _Pending(
            custom_id=f"{meta.get('ticket', 'x')}-{task}-{uuid.uuid4().hex[:8]}",
            provider=prov,
            req=req,
            output=output,
        )
        # Entra na fila e acorda o coordenador para ele reavaliar se a rodada pode fechar.
        with self._cond:
            self._pending.append(p)
            self._cond.notify_all()
        # Bloqueia este pipeline até o coordenador entregar a resposta (ou o erro).
        p.ready.wait()
        if p.error:
            raise p.error
        return p.obj, p.call  # type: ignore[return-value]

    def _coordinate(self) -> None:
        """Laço da thread coordenadora: decide quando fechar uma rodada e enviá-la como lote.

        A rodada fecha quando todos os pipelines ativos estão esperando (`len(_pending) >= _active`) ou quando a
        chamada mais antiga da fila passou de [batch.batch_collect_window_s]. A fila é separada por provedor
        (um lote por provedor); se o lote inteiro falhar, o erro volta para cada pipeline que estava esperando.
        """
        window = self.cfg.batch.batch_collect_window_s
        while True:
            with self._cond:
                # Espera até a rodada poder fechar (ou até pedirem para encerrar).
                while not self._stop:
                    # Todos os pipelines ativos já pediram algo: não vai chegar mais nada nesta rodada.
                    all_waiting = self._pending and len(self._pending) >= self._active
                    # A chamada mais antiga já esperou a janela inteira: envia o que tiver.
                    expired_window = (
                        self._pending
                        and time.monotonic() - self._pending[0].created >= window
                    )
                    if all_waiting or expired_window:
                        break
                    self._cond.wait(timeout=0.2)
                if self._stop:
                    return
                # Esvazia a fila de uma vez: o que chegar a partir daqui vai para a próxima rodada.
                batch, self._pending = self._pending, []
            # Um lote por provedor (cada um tem a sua API de lote).
            by_provider: dict[str, list[_Pending]] = {}
            for p in batch:
                by_provider.setdefault(p.provider, []).append(p)
            for prov, items in by_provider.items():
                try:
                    self._run(prov, items)
                except (
                    Exception
                ) as e:  # falha do lote inteiro: devolve o erro a cada pipeline
                    log.exception("falha no lote")
                    for p in items:
                        if not p.ready.is_set():
                            p.error = e
                            p.ready.set()

    def _run(self, prov: str, items: list[_Pending]) -> None:
        """Envia um lote a um provedor, espera terminar e entrega cada resultado ao pipeline que o pediu.

        Args:
            prov: nome do provedor.
            items: chamadas pendentes desse provedor; cada uma recebe `obj` e `call` (ou `error`) e é liberada.

        Raises:
            ProviderError: o lote não terminou dentro de [batch.batch_max_hours].
        """
        provider = self.provider(prov)
        start, t0 = datetime.now(), time.perf_counter()
        # Envia todas as requisições da rodada como um único lote.
        batch_id = provider.create_batch(
            [(p.custom_id, p.req, p.output) for p in items]
        )
        self.batches.append(batch_id)
        event(
            "batch_sent",
            provider=prov,
            batch_id=batch_id,
            requests=len(items),
            tasks=sorted({p.req.task for p in items}),
        )

        # Consulta o lote a cada [batch.batch_poll_interval_s] até terminar ou estourar o prazo máximo.
        deadline = time.monotonic() + self.cfg.batch.batch_max_hours * 3600
        every = self.cfg.observability.heartbeat_s
        last = time.monotonic()
        while not provider.batch_finished(batch_id):
            if time.monotonic() > deadline:
                raise ProviderError(f"lote {batch_id} não terminou no prazo")
            if every > 0 and time.monotonic() - last >= max(
                every, 60
            ):  # lote leva minutos: no máximo um aviso por minuto
                event(
                    "batch_waiting",
                    provider=prov,
                    batch_id=batch_id,
                    elapsed_s=round(time.perf_counter() - t0),
                )
                last = time.monotonic()
            time.sleep(self.cfg.batch.batch_poll_interval_s)
        dur = time.perf_counter() - t0
        event("batch_done", provider=prov, batch_id=batch_id, duration_s=round(dur, 1))
        # Distribui as respostas: cada pipeline recebe a sua (ou o erro) e é liberado com `ready.set()`.
        results = provider.batch_results(
            batch_id, {p.custom_id: p.output for p in items}
        )
        for p in items:
            r = results.get(
                p.custom_id,
                ProviderError(f"[{p.req.task}] sem resultado no lote {batch_id}"),
            )
            if isinstance(r, Exception):
                p.error = r
            else:
                self._store(prov, p.req, p.output, r)
                p.obj, p.call = r.obj, self._call(
                    prov, p.req, p.output, r.obj, r, dur, start
                )
            p.ready.set()


# --------------------------------------------------------------------------- sessão por chamado
class LlmSession:
    """Chamadas de um único chamado: escolhe o modelo da tarefa, calcula o custo e guarda o rastro.

    Attributes:
        client: cliente de LLM compartilhado (provedor, lote ou simulado).
        cfg: configuração (prompts, modelos, limites de tempo).
        ticket_id: id do chamado, enviado em `meta` de cada chamada.
        costs: conversão de tokens em custo.
        calls: rastro de todas as chamadas feitas para o chamado, na ordem; vai para o parecer.
    """

    def __init__(self, client: LlmClient, cfg: Settings, ticket_id: str):
        """
        Args:
            client: cliente de LLM usado nas chamadas.
            cfg: configuração do ambiente.
            ticket_id: id do chamado analisado.
        """
        self.client = client
        self.cfg = cfg
        self.ticket_id = ticket_id
        self.costs = CostCalculator(cfg)
        self.calls: list[LlmCall] = []

    def system(self, task: str) -> str:
        """Prompt de sistema da tarefa (config/prompts.toml, em português), depois do preâmbulo comum de engenheiro.

        Args:
            task: nome da tarefa; precisa existir um campo de mesmo nome em [prompts].

        Returns:
            [prompts.engineer] + linha em branco + prompt da tarefa (só o da tarefa, se o preâmbulo estiver vazio).
        """
        # Preâmbulo comum a todas as tarefas (o papel de engenheiro) + o prompt específico da tarefa.
        engineer = self.cfg.prompts.engineer.strip()
        task_prompt = getattr(self.cfg.prompts, task).strip()
        return f"{engineer}\n\n{task_prompt}" if engineer else task_prompt

    def model_for_task(self, task: str, fast: bool) -> tuple[str, str | None]:
        """Modelo da tarefa (sobrescrita em [models.tasks] ou o papel principal/rápido) e o de contingência do papel.

        Args:
            task: nome da tarefa.
            fast: True usa o papel "fast" ([models.fast]); False, o "main" ([models.main]).

        Returns:
            (modelo a usar, modelo de contingência do papel ou None).
        """
        role = "fast" if fast else "main"
        # Sobrescrita por tarefa em [models.tasks] vence; senão, o modelo do papel (principal ou rápido).
        model = self.cfg.models.tasks.get(task) or getattr(self.cfg.models, role)
        return model, self.cfg.models.fallback.get(role) or None

    def ask(
        self,
        task: str,
        parts: list[Part],
        output: type[T],
        *,
        system: str | None = None,
        fast: bool = False,
        max_tokens: int = 4000,
        meta: dict[str, Any] | None = None,
    ) -> T:
        """Pede uma saída estruturada para a tarefa, com o modelo da tarefa, custo e registro no log.

        Resposta cortada no limite de tokens de saída: uma nova tentativa com o dobro do limite (até MAX_OUTPUT_TOKENS).

        Args:
            task: nome da tarefa (define o prompt de sistema e o modelo, salvo sobrescrita).
            parts: conteúdo do pedido (texto, imagens e PDFs).
            output: modelo Pydantic esperado na resposta.
            system: prompt de sistema; None usa `self.system(task)`.
            fast: True usa o modelo rápido; False, o principal.
            max_tokens: limite de tokens de saída da primeira tentativa.
            meta: dados extras de rastreio, somados ao id do chamado.

        Returns:
            O objeto validado do tipo `output`, com os textos livres em linguagem simples (`plain_language`).

        Raises:
            ProviderError: erro do provedor (inclusive `LlmTimeout`) que a nova tentativa não resolveu.
        """
        try:
            return self._ask(
                task,
                parts,
                output,
                system=system,
                fast=fast,
                max_tokens=max_tokens,
                meta=meta,
            )
        except providers.ProviderError as e:
            # Só a resposta cortada no limite de saída ganha nova tentativa, com o dobro do limite (até o teto).
            bigger = min(MAX_OUTPUT_TOKENS, 2 * max_tokens)
            if not e.truncated or bigger <= max_tokens:
                raise
            event(
                "llm_truncated_retry",
                logging.WARNING,
                task=task,
                max_tokens=max_tokens,
                retry_max_tokens=bigger,
            )
            return self._ask(
                task,
                parts,
                output,
                system=system,
                fast=fast,
                max_tokens=bigger,
                meta=meta,
            )

    def _ask(
        self,
        task: str,
        parts: list[Part],
        output: type[T],
        *,
        system: str | None,
        fast: bool,
        max_tokens: int,
        meta: dict[str, Any] | None,
    ) -> T:
        """Uma tentativa de `ask`: escolhe o modelo, aplica o limite de tempo, calcula o custo e registra a chamada.

        Variáveis principais:
            limit: limite de cada tentativa no provedor (`call_timeout`, pelo tamanho do pedido).
            deadline: limite do vigia, com folga para uma nova tentativa do SDK (2 × limit + até 15 s).
            watched: só chamadas síncronas de verdade têm vigia; simulado e lote não (o lote leva horas).
            stalled: batidas do aviso "ainda aguardando" até o log marcar possível travamento.

        Os argumentos passados ao client.structured:
            system: prompt de sistema informado ou o da tarefa (`self.system`).
            meta: id do chamado + dados extras de rastreio.
            fallback: modelo de contingência do papel (principal ou rápido).
            timeout_s: `limit`, o limite de cada tentativa no provedor.
        """
        model, fallback = self.model_for_task(task, fast)
        # Quantos anexos vão no pedido: entram no cálculo do tempo limite.
        images = sum(isinstance(p, providers.ImagePart) for p in parts)
        docs = sum(isinstance(p, providers.DocumentPart) for p in parts)
        # no terminal: "chamando..." e, se demorar, "ainda aguardando há N s" (no simulado não há chamada de verdade)
        beat = self.cfg.observability.heartbeat_s
        # limite pelo tamanho do pedido; o vigia dá uma nova tentativa de folga e não vale no envio em lote (que leva horas)
        limit = call_timeout(self.cfg, images, docs, max_tokens)
        deadline = 2 * limit + min(15, limit)
        watched = not self.client.simulated and not self.client.via_batch
        stalled = (
            max(3, int(0.6 * deadline / beat) + 1) if beat > 0 else 3
        )  # "possível travamento" perto do limite, não antes
        watch = (
            waiting(
                "llm",
                beat,
                stalled_after=stalled,
                task=task,
                model=model,
                images=images,
                documents=docs,
                timeout_s=deadline,
            )
            if watched
            else nullcontext()
        )

        def call() -> tuple[T, LlmCall]:
            return self.client.structured(
                task=task,
                system=system or self.system(task),
                parts=parts,
                output=output,
                model=model,
                max_tokens=max_tokens,
                meta={"ticket": self.ticket_id, **(meta or {})},
                fallback=fallback,
                timeout_s=limit,
            )

        # Faz a chamada: com vigia (desiste em `deadline`) no síncrono real; direta no simulado e no lote.
        with watch:
            obj, ch = (
                run_with_deadline(call, deadline, f"[{task}] O modelo")
                if watched
                else call()
            )
        # Custo só para chamadas reais: simulado e cache não consomem tokens.
        if not ch.simulated and not ch.from_cache:
            ch.cost_usd = self.costs.usd(
                ch.model,
                ch.input_tokens,
                ch.output_tokens,
                ch.cache_read_tokens,
                ch.cache_write_tokens,
                ch.via_batch,
            )
        obj = plain_language(
            obj
        )  # textos livres sem nomes internos de campos nem termos em inglês
        # Guarda o rastro (vai para o parecer) e registra a chamada no log estruturado.
        self.calls.append(ch)
        event(
            "llm_call",
            task=task,
            model=ch.model,
            resolved_model=ch.resolved_model,
            duration_s=ch.duration_s,
            input_tokens=ch.input_tokens,
            output_tokens=ch.output_tokens,
            cache_read_tokens=ch.cache_read_tokens,
            cost_usd=ch.cost_usd,
            from_cache=ch.from_cache,
            via_batch=ch.via_batch,
            simulated=ch.simulated,
            prompt_version=ch.prompt_version,
            prompt_hash=ch.prompt_hash,
        )
        return obj
