# Atest.AI: código, dataset sintético e painel de demonstração

Implementa o fluxo da apresentação v26. Cada chamado passa pelo **checklist mínimo**, por três validações (**escopo**, **orçamento × escopo** e **evidências fotográficas**) e recebe um **score de 0 a 100** pela régua do deck. O resultado é um **parecer** em modo copiloto: o modelo aponta, a régua decide, a pessoa analista confirma.

Todos os dados são fictícios: agências, fornecedores, CNPJs, valores e fotos.

## Como rodar

```bash
pip install -r requirements.txt
cp config/.secrets.toml.example config/.secrets.toml   # chaves de API (só para o modo API)
python main.py                                         # painel em http://localhost:8000
```

`main.py` não recebe argumentos: o que ele faz vem de `config/settings.toml` (`[default.execution] action`):

| `action` | O que faz |
|---|---|
| `"panel"` | sobe o painel web |
| `"batch"` | roda os chamados e grava pareceres, CSV e métricas em `output/runs/<id>/` |
| `"validate"` | roda o conjunto de validação e aplica o **portão de qualidade**; sai com código 1 se reprovar (use no CI) |

Outros comandos:
- `python -m pytest -q`: 32 testes (regras, planilhas, integridade das fotos, pipeline, SDK com servidor falso, Message Batches, provedores, roteamento e contingência, métricas, API do painel, gerador de fotos).
- `python examples/api_smoke_test.py`: duas chamadas rápidas (texto e foto) para validar a chave e o modelo.
- `python examples/copilot_flow_langgraph.py`: o fluxo de revisão humana em LangGraph (veja abaixo).

## Padrões de código

- **Código em inglês** (módulos, classes, funções, variáveis, campos, chaves de configuração, colunas do banco, rotas da API, valores de enum). **Comentários, docstrings, prompts, mensagens e textos de tela em português do Brasil.**
- Os prompts (`config/prompts.toml`) e as descrições dos campos das saídas estruturadas (`atest/llm_schemas.py`) são instruções ao modelo e ficam em português; quando citam um campo ou valor do esquema, usam o nome em inglês (ex.: `vague_scope`, `"yes"`/`"no"`).
- O contrato com quem preenche o orçamento continua em português: abas `Chamado`/`Itens`, tabelas `tbChamado`/`tbItens` e os rótulos das colunas.
- PEP 8 com `ruff` (`ruff check` e `ruff format`, configuração em `pyproject.toml`); tipagem em todo o código; Pydantic v2 nos modelos de domínio, configuração e saídas do modelo.
- Orientação a objetos onde há estado ou variação de comportamento (veja **Arquitetura**); funções puras para utilitários pequenos (`formatting.py`, hashing de imagens).

## Arquitetura

```
Application (main.py)
 └─ BatchRunner ─── ComponentFactory ─→ LlmClient (ProviderClient | BatchClient | SimulatedClient)
     │                                → PhotoIndex (hashes do histórico, com HashCache)
     │                                → Orchestrator
     ├─ Orchestrator ─ AnalysisContext (estado de um chamado)
     │   └─ AnalysisStage (ABC), em ordem:
     │       ChecklistStage → ScopeStage → QuoteStage → PhotoStage → ScoringStage → AssessmentStage
     │       (cada etapa recebe Settings, References e ScoreCalculator; o checklist pode encerrar a análise)
     ├─ RunOutputWriter (output/runs/<id>/)
     ├─ GroundTruthEvaluator + ValidationReporter (métricas e portão de qualidade)
     └─ Database (SQLite)
```

Trocar, remover ou acrescentar uma etapa é passar outra lista em `Orchestrator(..., stages=[...])`. Toda etapa herda de `AnalysisStage` e implementa `run(ctx)`.

## Configuração (Dynaconf + TOML)

| Arquivo | Conteúdo |
|---|---|
| `config/settings.toml` | execução, modelos e provedores, lote/batch, caminhos, painel, validação, observabilidade, custos |
| `config/rubric.toml` | pesos 20/40/40, faixas 85/70, descontos por severidade, tipos de apontamento, tolerâncias |
| `config/checklists.toml` | itens obrigatórios por categoria × tipo de manutenção × momento |
| `config/prompts.toml` | os prompts de sistema de cada tarefa (em português), com versão |
| `config/.secrets.toml` | chaves de API e credenciais da IARA (fora do git) |
| `config/settings.local.toml` | ajustes só desta máquina, ex.: usar a IARA dentro do Itaú (fora do git; modelo em `config/settings.itau.toml.example`) |

Ambientes `[default]`, `[development]` e `[production]`, escolhidos por `ATEST_ENV`. Qualquer chave pode ser sobrescrita por variável de ambiente: `ATEST_MODELS__MAIN="openai:<modelo>"`, `ATEST_PIPELINE__PHASE=1`. Tudo é validado por Pydantic ao carregar (`atest/config.py`): erro de digitação no TOML falha na hora, não no meio de um lote.

## Trocar de LLM: Anthropic, OpenAI, Gemini ou IARA

O pipeline não conhece nenhum SDK. Ele monta uma `Request` neutra (texto, imagens e PDFs como `TextPart`, `ImagePart`, `DocumentPart`) e pede uma saída Pydantic; cada provedor em `atest/providers/` traduz para a sua API de saída estruturada:

| Provedor | Saída estruturada | Lote assíncrono |
|---|---|---|
| `anthropic` | `messages.parse(output_format=...)`, prompt de sistema com cache | Message Batches API (−50%) |
| `openai` | Responses API, `responses.parse(text_format=...)` | — (cai para síncrono) |
| `google` | `google-genai`, `response_schema=<Pydantic>` | — (cai para síncrono) |
| `iara` | IARA GenAI (Itaú), `chat.completions.create` com `response_format` JSON Schema estrito | — (cai para síncrono) |

Trocar é só configuração, no formato `"provedor:modelo"`:

```toml
[default.models]
main = "anthropic:claude-sonnet-5-5"   # escopo, orçamento, fotos
fast = "anthropic:claude-haiku-5-5"    # anexos, redação do parecer

[default.models.tasks]                 # um modelo diferente por tarefa
photos = "google:<modelo-gemini>"

[default.models.fallback]              # usado só em erro transitório (sobrecarga, limite de taxa)
main = "openai:<modelo-openai>"
```

Um provedor novo é uma subclasse de `Provider` com `generate(request, output)` e uma linha em `providers.register("nome", fabrica)`. Opções próprias dele ficam em `[default.llm.provider_options.<nome>]` e chegam como argumentos da fábrica. O painel mostra quais provedores a configuração usa e avisa se falta credencial.

### Rodando no Itaú (IARA GenAI)

Dentro do banco, todo LLM passa pela IARA. Fora dele, nada muda (Anthropic). O pipeline, o painel, os custos, o cache e a validação são os mesmos; só a configuração troca.

1. Instale o SDK pelo Artifactory interno: `pip install iara_genai_sdk` (mais `pypdf`, se for usar `pdf_mode = "text"`).
2. Credenciais da aplicação em `config/.secrets.toml` (`iara_client_id`, `iara_client_secret` e, opcional, `iara_access_token`) ou nas variáveis `IARA_CLIENT_ID`, `IARA_CLIENT_SECRET` e `IARA_ACCESS_TOKEN`.
3. `cp config/settings.itau.toml.example config/settings.local.toml`. Esse arquivo fica fora do git e é carregado depois do `settings.toml`; ele troca os modelos para `iara:gpt-4.1` e escolhe o ambiente da IARA (`dev`, `homol` ou `prod`). Com `ATEST_ENV=production`, o ambiente vira `prod`.
4. Antes de rodar o lote, teste com `python examples/api_smoke_test.py`.

Modelos: o catálogo da IARA fica em `[default.llm.provider_options.iara.models]`, agrupado por backend (`azure_openai`, `bedrock`, `vertex`), como na página "Modelos" da documentação. Com a IARA escolhida, o painel lista esses modelos com campo de busca. `iara:claude-sonnet-5` vai sozinho para o `bedrock`. Um modelo fora do catálogo usa o backend padrão (`provider = "azure_openai"`), e `iara:bedrock/<modelo>` força o backend. Os modelos em `text_only` não leem imagem: o painel os marca como "só texto", e o adaptador os recusa, com erro claro, nas tarefas com fotos e anexos. Eles servem para tarefas de texto em `[models.tasks]` (`scope`, `quote_review`, `assessment`). Ficaram fora do catálogo os embeddings, o áudio, a geração de imagem e os modelos `-batch`. Se o backend recusar alguma coisa, ajuste em `[default.llm.provider_options.iara]`, sem mexer no código:

| Opção | Padrão | Alternativas |
|---|---|---|
| `json_mode` | `"json_schema"` (schema estrito no `response_format`) | `"json_object"` (JSON livre e schema no prompt) · `"prompt"` (sem `response_format`) |
| `pdf_mode` | `"file"` (PDF enviado como arquivo) | `"text"` (texto extraído localmente com `pypdf`) |
| `enable_polling` | `true` | `false` |

Alguns modelos pela IARA (ex.: Claude via Bedrock) devolvem campos lista/objeto como string com JSON dentro, às vezes com o objeto inteiro repetido (`{"attachments": "{\"attachments\": [...]}"}`). O adaptador corrige isso antes de validar, só onde o schema pede lista/objeto, e registra o evento `iara_json_repaired` no log. Texto livre que não é JSON continua sendo erro.

A Batch API da IARA ainda não está integrada: no modo Lote, as chamadas para `iara:` saem síncronas e sem o desconto de lote. Os preços em `[default.costs.prices."iara:gpt-4.1"]` são os de lista da OpenAI, só como referência.

## LangChain e LangGraph: onde (não) usar

**Não usamos no pipeline de análise, de propósito.** Ele é uma sequência fixa (checklist → escopo → orçamento → fotos → score → parecer), com decisão por regra e saídas estruturadas. A camada própria de provedores mantém o que importa aqui e que um framework esconderia ou dificultaria: Message Batches (−50% no batch horário), cache de prompt, custo por chamada, rastro de cada chamada com versão e hash, e testes com o SDK real contra um servidor falso.

**LangGraph faz sentido no fluxo em volta da análise**, e `examples/copilot_flow_langgraph.py` mostra isso rodando:
- **pausa para a pessoa analista** (modo copiloto) que pode durar dias, com `interrupt()`, sem prender processo;
- **estado durável** entre pausa e retomada (checkpointer; em produção, Postgres, com `thread_id` = id do chamado);
- **ciclo**: pedir complemento ao fornecedor, esperar o reenvio e analisar de novo;
- **roteamento**: checklist incompleto volta direto ao fornecedor; aprovado segue; o resto vai para a fila.

O `Orchestrator` inteiro vira um único nó do grafo. Também passa a valer a pena se a análise virar agente (o modelo decidindo consultar a LPU, o histórico da agência ou pedir outra foto).

## Boas práticas de versionamento e uso de LLM aplicadas

- **Prompts versionados** em `config/prompts.toml` (`version`); cada chamada grava `prompt_version`, `prompt_hash` (do texto efetivo) e `schema_hash` (da saída Pydantic).
- **Modelo efetivo registrado**: além do alias configurado, cada chamada grava o `resolved_model` devolvido pelo provedor. Em produção, fixe snapshots datados.
- **Assinatura da configuração**: `cfg.signature()` resume régua + prompts + modelos + parâmetros. Vai em cada parecer e em cada rodada de validação, para comparar versões lado a lado.
- **Portão de qualidade antes de publicar**: mudou prompt, régua ou modelo? `action = "validate"` roda o conjunto de validação e reprova se acurácia, kappa, F1 dos apontamentos ou erro do score passarem dos limites de `[validation]`.
- **Saída estruturada sempre** (JSON Schema a partir do Pydantic), com as descrições dos campos servindo de instrução.
- **O modelo aponta, a régua decide**: preço × LPU, duplicidade, hash e data das fotos, notas, score e recomendação são regra, auditáveis e reprodutíveis.
- **Cache** de prompt (provedor) e cache em disco das respostas (chave = provedor + modelo + prompt + conteúdo + schema).
- **Contingência** só em erro transitório; erro definitivo não troca de modelo e aparece.
- **Custo por chamado** em USD e BRL, com desconto de batch; **observabilidade** em JSON lines com ids de execução e chamado; persistência em SQLite.
- **Feedback do copiloto** (aceitar, ajustar, discordar) gravado por parecer: vira dado rotulado para a próxima validação.

## O painel

- **Análise**: lista de chamados (filtro por conjunto e esteira), modo simulado ou API, régua Fase 1/2, síncrono ou batch. Abas: parecer (carimbo, notas, apontamentos, mensagem ao fornecedor, feedback), orçamento × escopo, fotos, chamadas ao modelo e entrada. **Novo chamado** envia planilha e fotos pela tela.
- **Validação**: roda um conjunto inteiro (ou uma amostra) e mostra a leitura de ciência de dados: portão de qualidade, acurácia com IC 95% por bootstrap, kappa de Cohen, F1 de "pegar problema", matriz de confusão, dispersão do score, precisão/cobertura/F1 por tipo de apontamento, acurácia por categoria, valor em questão, latência e custo p50/p95, e os casos divergentes.
- **Operação**: histórico de execuções, custos e feedbacks.

Front-end em React + TypeScript + Tailwind (Vite), em `panel/`. Para alterar: `cd panel && npm install && npm run dev` (proxy de `/api` para `:8000`); `npm run build` gera `panel/dist`, servido pelo FastAPI. Rotas da API: `/api/tickets`, `/api/runs`, `/api/assessments`, `/api/datasets`, `/api/validations`, `/api/metrics`, `/api/spreadsheet-template` e, com login, `/api/admin/*`.

### Configuração (portal com login)

A aba **Configuração** do painel é o portal para manter as regras sem editar arquivo: checklist mínimo por categoria × tipo de manutenção × etapa da esteira (ativar/desativar regras e exigências, criar regras, ajustar os tipos de anexo aceitos), regras de apontamento (ativar/desativar, severidade, fase, trava, redução de confiança), régua do score (pesos, descontos, faixas, confiança, tolerâncias), além de consulta a categorias, sintomas e LPU.

- **Acesso:** usuário e senha (PBKDF2; sessão em token que expira em `admin.session_hours`; bloqueio temporário após `admin.max_failed_logins` erros). O primeiro usuário vem de `[default.admin].seed_users` em `config/settings.toml`, que guarda só o hash. Troque a senha inicial pelo próprio portal (Usuários e senha).
- **Como as mudanças valem:** cada "Salvar" exige um motivo e grava uma versão completa da seção no banco (`config_versions`). A configuração efetiva é a dos TOML com a última versão por cima; os arquivos em `config/` continuam sendo o padrão de fábrica ("Restaurar padrão"). O histórico mostra autor, motivo e o resumo do que mudou, e permite voltar a qualquer versão.
- **Rastreabilidade:** a assinatura da configuração (gravada em cada parecer e em cada rodada de validação) inclui régua e checklist; a versão da régua ganha o sufixo `+portal.N`. `python main.py` (lote e validação) também aplica as versões salvas.

## Contrato de entrada

Cada chamado (`data/tickets/<id>/ticket.json`, modelo Pydantic `Ticket`) tem obrigatoriamente **categoria** (`painting`, `waterproofing`, `electrical`, `lighting`, `air_conditioning`, `plumbing`, `metalwork`, `cctv`, `alarm`, `cctv_and_alarm`), **sintoma** macro e **escopo** em linguagem natural.

O **orçamento é sempre Excel**, com duas abas em formato Tabela: `Chamado`/`tbChamado` (Campo, Valor: chamado, esteira, agência, fornecedor, CNPJ, nº, data, categoria, sintoma, escopo, valor total) e `Itens`/`tbItens` (Item, Descrição, Unidade, Quantidade, Valor unitário, Valor total). A leitura é por regra, sem LLM (`repository.read_quote`). Divergência entre planilha e chamado vira o apontamento `spreadsheet_mismatch`. O painel oferece o modelo da planilha para download.

## Dados

- **Demonstração** (13 chamados, `00…`): os casos do deck e variações, com gabarito escrito à mão.
- **Validação** (80 chamados, `0100…`): 10 modelos de serviço × 8, com defeitos injetados por sorteio. O gabarito é calculado pela própria régua a partir dos defeitos.
- **Itaú** (20 chamados, `0200…`): a mesma mecânica da validação (10 modelos × 2, defeitos sorteados, gabarito pela régua), em agências no padrão Itaú e com **fotos fotorrealistas geradas por IA** com a identidade visual do banco. Agências, fornecedores, CNPJs e valores continuam fictícios; a marca aparece só para demonstração interna.

Regerar: `python generator/build_demo_dataset.py --clean` e depois `python generator/build_validation_dataset.py`.

Conjunto Itaú (precisa de `openai_api_key` em `config/.secrets.toml`):

```bash
python generator/build_itau_dataset.py --needs                        # quantas fotos cada cena precisa (hoje 47, em 24 cenas)
python generator/ai_photos.py --profile itau --from-needs --dry-run   # confere quantidade e custo (≈ US$ 3)
python generator/ai_photos.py --profile itau --from-needs             # gera as fotos em data/real_photos_itau/ (cobrado)
python generator/build_itau_dataset.py                                # gera os chamados 0200xxxx
```

O gerador do Itaú roda em modo *strict*: se faltar foto para alguma cena, ele para e diz qual chave gerar, em vez de cair no desenho. Continuam desenhados só o que tem texto que precisa bater com o chamado: etiqueta da luminária, teclado da central, termo de conclusão, relatório de preventiva e o texto (câmera, data e hora) por cima das imagens de CFTV. A imagem da câmera é foto.

### Fotos

Nos conjuntos de demonstração e de validação, as cenas são desenhadas por código e passam por uma **simulação de câmera de celular** (`generator/camera.py`). Ficam mais próximas de foto, mas continuam sendo ilustrações. Para fotos reais ou fotorrealistas, o gerador aceita uma pasta por cena em `data/real_photos/<chave>/` (chaves e descrições em `generator/real_photos.py`): fotos reais de chamados antigos (sem nomes, placas e rostos) ou fotos geradas por modelo de imagem com `python generator/ai_photos.py` (`--list` mostra o que já existe; cada imagem é cobrada pelo provedor).

O conjunto Itaú usa outro **perfil** de fotos (`--profile itau`): pasta própria (`data/real_photos_itau/`), prompt com a identidade visual do Itaú (laranja, azul-marinho, logo onde a cena permite) e descrições de cena ajustadas. Assim as fotos de um perfil nunca são consumidas pelo outro. Com fotos reais, o gerador não espelha a imagem (o logo ficaria invertido) e não desenha os detalhes de variação por cima.

## Estrutura do código

```
main.py                  Application: painel, lote ou validação (sem argumentos; tudo vem do TOML)
config/                  settings, rubric, checklists, prompts (TOML)
atest/
  config.py              Dynaconf → Settings (Pydantic), assinatura, chaves por provedor
  domain.py              domínio: Ticket, Quote, Rubric, Finding, Assessment, LlmCall...
  llm_schemas.py         saídas estruturadas pedidas ao modelo (descrições em português)
  providers/             Provider (ABC) + anthropic, openai, google, iara
  llm.py                 ProviderClient (cache, contingência), BatchClient (lotes), LlmSession (roteamento, custo, rastro)
  simulated.py           SimulatedClient: responde pelo gabarito, com ruído opcional
  analysis.py            AnalysisContext e AnalysisStage (contrato das etapas)
  checklist.py scope.py quote.py photos.py scoring.py assessment.py   as etapas
  score.py               ScoreCalculator (régua: apontamentos → notas, score, recomendação)
  pipeline.py            Orchestrator de um chamado
  batch.py               ComponentFactory, BatchRunner, RunOutputWriter
  evaluation.py          GroundTruthEvaluator
  validation.py          ValidationReporter, Stats, DatasetCatalog
  database.py            Database (SQLite): execuções, pareceres, chamadas, feedbacks, validações
  costs.py formatting.py observability.py spreadsheet.py repository.py attachments.py api.py
panel/                   React + TS + Tailwind; dist/ compilado
generator/               cenas, câmera, fotos reais, planilhas, casos de demonstração e de validação
examples/                teste rápido de API e fluxo do copiloto em LangGraph
tests/
```

## Limitações

- O modo simulado responde pelo gabarito e **não mede a qualidade do modelo**; serve para demonstrar fluxo e métricas. A medida real é `action = "validate"` em modo API, idealmente com chamados históricos no formato de `data/tickets/<id>/`.
- O limiar de semelhança das fotos (`hash_max_distance`, e o mais estrito para fotos com pouco detalhe) foi calibrado em fotos sintéticas; recalibre com fotos reais.
- Os provedores OpenAI e Gemini estão testados na conversão de conteúdo, não contra a API real (não havia chave neste ambiente).
- O provedor IARA foi escrito a partir da documentação interna e testado com um cliente falso (pipeline completo, síncrono e lote). Ainda não rodou contra a IARA real. Os pontos a confirmar dentro do banco são o suporte a `response_format` com JSON Schema, PDF como arquivo e os nomes dos campos de uso de tokens e das exceções do SDK.
- Bancos SQLite criados pela versão em português (`saida/atest.db`) não são compatíveis com o novo esquema; a versão atual cria `output/atest.db`.
