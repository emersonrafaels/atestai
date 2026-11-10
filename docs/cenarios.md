# Cenários de teste

Gerado por `python generator/build_scenarios_dataset.py` (não edite à mão). No painel, a aba **Cenários** mostra o mesmo
catálogo, com filtro e seleção dos chamados para analisar.

## Catálogo (um chamado por cenário, conjunto `scenarios`)

| Chamado | Cenário | O que testa | Esperado | Score | Apontamentos esperados |
|---|---|---|---|---|---|
| `03000001` | Chamado limpo (predial) | Pintura sem nenhum problema: deve ser aprovado. | Aprovar | 100 | — |
| `03000002` | Chamado limpo (segurança) | Câmera desfocada, serviço comprovado: deve ser aprovado. | Aprovar | 100 | — |
| `03000003` | Aprovação de orçamento limpa | Orçamento antes da execução, sem problemas. | Aprovar | 100 | — |
| `03000004` | Escopo vago | O texto não diz o que fazer nem onde ("Verificar ... Urgente."). | Aprovar | 93 | Escopo vago ou sem ambiente definido |
| `03000005` | Escopo incoerente | O sintoma informado não combina com a categoria. | Aprovar | 97 | Escopo incoerente com a categoria ou o sintoma |
| `03000006` | Escopo mal preenchido | Vago e incoerente ao mesmo tempo: dois redutores de confiança levam à análise detalhada. | Análise detalhada | 90 | Escopo incoerente com a categoria ou o sintoma, Escopo vago ou sem ambiente definido |
| `03000007` | Item fora do escopo | Orçamento cobra serviço que não foi pedido. | Aprovar | 86 | Item fora do escopo |
| `03000008` | Troca sem justificativa | Pedido de limpeza e ajuste, orçamento cobra câmera nova. | Aprovar com ressalvas | 80 | Valor potencial divergente relevante no orçamento, Troca ou peça sem justificativa técnica |
| `03000009` | Preço acima da referência | Um item acima da LPU + tolerância. | Aprovar | 94 | Preço acima da referência |
| `03000010` | Quantidade acima do esperado | Mais lâmpadas do que o escopo pede. | Aprovar | 94 | Quantidade acima do esperado |
| `03000011` | Item duplicado | O mesmo item cobrado em duas linhas. | Aprovar | 86 | Item cobrado em duplicidade |
| `03000012` | Planilha divergente | Valor ou sintoma da planilha diferente do chamado. | Aprovar | 94 | Planilha divergente do chamado (categoria, sintoma, escopo ou valor) |
| `03000013` | Orçamento com vários erros | Fora do escopo, preço acima, quantidade acima e duplicidade no mesmo orçamento. | Devolver ao fornecedor | 60 | Item cobrado em duplicidade, Item fora do escopo, Preço acima da referência, Quantidade acima do esperado, Valor potencial divergente relevante no orçamento |
| `03000014` | Orçamento com erros na aprovação | Etapa de orçamento (antes da execução) com item fora do escopo e preço acima. | Aprovar com ressalvas | 80 | Item fora do escopo, Preço acima da referência |
| `03000015` | Foto de outro ambiente | Uma foto mostra outro cômodo ou a fachada. | Aprovar | 86 | Foto não corresponde ao escopo |
| `03000016` | Sem foto do depois | Nenhuma foto prova o serviço concluído. | Aprovar | 86 | Sem foto do serviço concluído |
| `03000017` | Foto do depois de outro ambiente | Falta a prova do serviço e há foto de outro ambiente: a régua desconta só uma vez (absorção). | Aprovar | 86 | Sem foto do serviço concluído, Foto não corresponde ao escopo |
| `03000018` | Sem foto do antes | Não há registro do estado anterior (Fase 2). | Aprovar | 94 | Sem foto do "antes" |
| `03000019` | Foto ilegível | Foto escura e tremida (Fase 2). | Aprovar | 98 | Foto ilegível |
| `03000020` | Foto reaproveitada | Foto de um chamado anterior: trava de integridade (Fase 2). | Devolver com trava | 76 | Foto reaproveitada de outro chamado |
| `03000021` | Foto com data anterior | EXIF anterior à abertura do chamado. | Aprovar | 94 | Foto com data anterior à abertura do chamado |
| `03000022` | Checklist incompleto | Falta documento obrigatório: volta antes da análise. | Devolvido no checklist | — | — |
| `03000023` | Problemas em todas as validações | Escopo vago, item fora do escopo, preço acima, foto de outro ambiente e foto ilegível. | Análise detalhada | 51 | Item fora do escopo, Foto não corresponde ao escopo, Preço acima da referência, Valor potencial divergente relevante no orçamento, Foto ilegível, Escopo vago ou sem ambiente definido |

## Por tipo de cenário, em todos os conjuntos

### Resultado esperado

| Cenário | Qtd. | Chamados |
|---|---|---|
| **Chamado limpo**<br>Nenhum apontamento esperado: o Atest.AI deve aprovar. | 44 | Demonstração: `00530121`, `00536640`; Itaú: `02000001`, `02000002`, `02000003`, `02000004`, `02000005`, `02000006`, `02000007`, `02000008`, `02000009`, `02000010`, `02000021`, `02000022`, `02000023`, `02000024`, `02000025`, `02000026`, `02000027`; Cenários: `03000001`, `03000002`, `03000003`; Validação: `01000001`, `01000002`, `01000003`, `01000004`, `01000005`, `01000006`, `01000007`, `01000008`, `01000009`, `01000010`, `01000011`, `01000013`, `01000018`, `01000031`, `01000032`, `01000049`, `01000055`, `01000056`, `01000058`, `01000067`, `01000071`, `01000078` |
| **Aprovar com ressalvas**<br>Problemas leves: score entre 70 e 84. | 25 | Demonstração: `00531877`, `00534519`, `00538890`; Itaú: `02000016`, `02000019`, `02000028`, `02000030`, `02000033`, `02000034`, `02000038`; Cenários: `03000008`, `03000014`; Validação: `01000016`, `01000024`, `01000027`, `01000028`, `01000033`, `01000036`, `01000040`, `01000042`, `01000043`, `01000050`, `01000053`, `01000065`, `01000074` |
| **Devolver ao fornecedor**<br>Score abaixo de 70. | 13 | Demonstração: `00482193`; Itaú: `02000015`, `02000018`, `02000035`, `02000040`; Cenários: `03000013`; Validação: `01000022`, `01000030`, `01000060`, `01000062`, `01000066`, `01000068`, `01000069` |
| **Devolver com trava**<br>Trava de integridade (foto reaproveitada). | 17 | Demonstração: `00517706`; Itaú: `02000014`, `02000017`, `02000020`, `02000036`, `02000037`; Cenários: `03000020`; Validação: `01000012`, `01000019`, `01000046`, `01000047`, `01000052`, `01000059`, `01000064`, `01000072`, `01000076`, `01000080` |
| **Análise detalhada**<br>Confiança baixa: entrada insuficiente para concluir. | 4 | Demonstração: `00533402`; Cenários: `03000006`, `03000023`; Validação: `01000079` |

### Escopo

| Cenário | Qtd. | Chamados |
|---|---|---|
| **Escopo mal preenchido**<br>Escopo vago ou incoerente com a categoria e o sintoma. | 23 | Demonstração: `00533402`, `00540277`; Itaú: `02000019`, `02000028`, `02000033`, `02000038`; Cenários: `03000004`, `03000005`, `03000006`, `03000023`; Validação: `01000019`, `01000024`, `01000026`, `01000030`, `01000034`, `01000043`, `01000044`, `01000060`, `01000063`, `01000068`, `01000072`, `01000076`, `01000079` |
| **Escopo vago**<br>Não dá para saber o que fazer, onde ou em quê. | 13 | Demonstração: `00533402`; Itaú: `02000019`, `02000038`; Cenários: `03000004`, `03000006`, `03000023`; Validação: `01000019`, `01000024`, `01000030`, `01000034`, `01000044`, `01000060`, `01000072` |
| **Escopo incoerente**<br>O sintoma informado não bate com a categoria ou o texto. | 11 | Demonstração: `00540277`; Itaú: `02000028`, `02000033`; Cenários: `03000005`, `03000006`; Validação: `01000026`, `01000043`, `01000063`, `01000068`, `01000076`, `01000079` |

### Orçamento

| Cenário | Qtd. | Chamados |
|---|---|---|
| **Orçamento com vários erros**<br>Dois ou mais tipos de problema no orçamento. | 42 | Demonstração: `00482193`, `00517706`, `00531877`, `00534519`; Itaú: `02000014`, `02000015`, `02000017`, `02000018`, `02000020`, `02000028`, `02000030`, `02000033`, `02000035`, `02000036`, `02000037`, `02000038`, `02000040`; Cenários: `03000008`, `03000013`, `03000014`, `03000023`; Validação: `01000020`, `01000022`, `01000023`, `01000025`, `01000030`, `01000033`, `01000036`, `01000042`, `01000052`, `01000053`, `01000060`, `01000062`, `01000064`, `01000065`, `01000066`, `01000068`, `01000069`, `01000072`, `01000074`, `01000076`, `01000080` |
| **Item fora do escopo**<br>Serviço, local ou equipamento que não foi pedido. | 30 | Demonstração: `00482193`, `00517706`; Itaú: `02000014`, `02000016`, `02000020`, `02000035`, `02000036`, `02000037`, `02000039`; Cenários: `03000007`, `03000013`, `03000014`, `03000023`; Validação: `01000022`, `01000024`, `01000027`, `01000030`, `01000033`, `01000042`, `01000052`, `01000053`, `01000060`, `01000062`, `01000064`, `01000066`, `01000068`, `01000069`, `01000072`, `01000074`, `01000076` |
| **Troca sem justificativa**<br>Troca de peça quando o pedido era ajuste ou reparo. | 5 | Demonstração: `00517706`; Itaú: `02000018`, `02000033`, `02000040`; Cenários: `03000008` |
| **Preço acima da referência**<br>Valor unitário acima da LPU + tolerância. | 28 | Demonstração: `00531877`, `00534519`, `00537215`; Itaú: `02000013`, `02000015`, `02000019`, `02000028`, `02000030`, `02000034`, `02000037`, `02000038`, `02000040`; Cenários: `03000009`, `03000013`, `03000014`, `03000023`; Validação: `01000020`, `01000023`, `01000025`, `01000030`, `01000041`, `01000052`, `01000059`, `01000060`, `01000065`, `01000070`, `01000073`, `01000077` |
| **Quantidade acima do esperado**<br>Mais do que o escopo permite. | 15 | Demonstração: `00482193`, `00531877`; Itaú: `02000012`, `02000015`, `02000028`, `02000030`, `02000035`, `02000037`, `02000038`; Cenários: `03000010`, `03000013`; Validação: `01000020`, `01000066`, `01000075`, `01000080` |
| **Item duplicado**<br>A mesma coisa cobrada duas vezes. | 22 | Demonstração: `00534519`; Itaú: `02000015`, `02000017`, `02000029`, `02000032`, `02000041`; Cenários: `03000011`, `03000013`; Validação: `01000016`, `01000022`, `01000030`, `01000036`, `01000040`, `01000043`, `01000045`, `01000050`, `01000052`, `01000065`, `01000068`, `01000069`, `01000076`, `01000080` |
| **Planilha divergente**<br>Planilha diferente do chamado (valor ou sintoma). | 19 | Demonstração: `00535003`, `00540277`; Itaú: `02000017`, `02000018`, `02000035`; Cenários: `03000012`; Validação: `01000012`, `01000015`, `01000023`, `01000025`, `01000028`, `01000029`, `01000034`, `01000036`, `01000054`, `01000064`, `01000066`, `01000072`, `01000080` |

### Fotos

| Cenário | Qtd. | Chamados |
|---|---|---|
| **Foto de outro ambiente**<br>Foto que não corresponde ao escopo. | 18 | Demonstração: `00482193`; Itaú: `02000014`, `02000019`, `02000028`, `02000030`, `02000034`, `02000040`; Cenários: `03000015`, `03000017`, `03000023`; Validação: `01000014`, `01000016`, `01000017`, `01000027`, `01000038`, `01000060`, `01000062`, `01000069` |
| **Sem foto do depois**<br>Nenhuma foto prova o serviço concluído. | 6 | Demonstração: `00517706`, `00538890`; Itaú: `02000018`; Cenários: `03000016`, `03000017`; Validação: `01000038` |
| **Sem foto do antes**<br>Nenhuma foto do estado anterior (Fase 2). | 9 | Demonstração: `00482193`, `00531877`; Cenários: `03000018`; Validação: `01000019`, `01000024`, `01000028`, `01000059`, `01000064`, `01000074` |
| **Foto ilegível**<br>Foto escura ou tremida (Fase 2). | 15 | Demonstração: `00533402`, `00538890`; Itaú: `02000013`, `02000017`; Cenários: `03000019`, `03000023`; Validação: `01000015`, `01000016`, `01000039`, `01000046`, `01000050`, `01000053`, `01000065`, `01000077`, `01000079` |
| **Foto reaproveitada**<br>Foto de outro chamado (Fase 2, trava). | 17 | Demonstração: `00517706`; Itaú: `02000014`, `02000017`, `02000020`, `02000036`, `02000037`; Cenários: `03000020`; Validação: `01000012`, `01000019`, `01000046`, `01000047`, `01000052`, `01000059`, `01000064`, `01000072`, `01000076`, `01000080` |
| **Foto com data anterior**<br>Data EXIF anterior à abertura do chamado. | 12 | Demonstração: `00517706`; Itaú: `02000016`; Cenários: `03000021`; Validação: `01000028`, `01000033`, `01000035`, `01000040`, `01000044`, `01000047`, `01000048`, `01000065`, `01000077` |

### Checklist

| Cenário | Qtd. | Chamados |
|---|---|---|
| **Checklist incompleto**<br>Falta documento obrigatório: volta antes da análise. | 10 | Demonstração: `00523310`, `00539412`; Itaú: `02000011`, `02000031`; Cenários: `03000022`; Validação: `01000021`, `01000037`, `01000051`, `01000057`, `01000061` |

### Combinações

| Cenário | Qtd. | Chamados |
|---|---|---|
| **Problemas em várias validações**<br>Apontamentos em duas ou mais validações (escopo, orçamento, fotos). | 50 | Demonstração: `00482193`, `00517706`, `00531877`, `00533402`, `00540277`; Itaú: `02000013`, `02000014`, `02000016`, `02000017`, `02000018`, `02000019`, `02000020`, `02000028`, `02000030`, `02000033`, `02000034`, `02000036`, `02000037`, `02000038`, `02000040`; Cenários: `03000023`; Validação: `01000012`, `01000015`, `01000016`, `01000019`, `01000024`, `01000027`, `01000028`, `01000030`, `01000033`, `01000034`, `01000040`, `01000043`, `01000044`, `01000050`, `01000052`, `01000053`, `01000059`, `01000060`, `01000062`, `01000064`, `01000065`, `01000068`, `01000069`, `01000072`, `01000074`, `01000076`, `01000077`, `01000079`, `01000080` |
| **Aprovação de orçamento**<br>Chamado na etapa de orçamento (antes da execução). | 34 | Demonstração: `00535003`; Itaú: `02000006`, `02000016`, `02000021`, `02000022`, `02000023`, `02000024`, `02000025`, `02000026`, `02000027`, `02000028`, `02000029`, `02000030`, `02000031`, `02000032`, `02000033`, `02000034`, `02000035`, `02000036`, `02000037`, `02000038`, `02000039`, `02000040`, `02000041`; Cenários: `03000003`, `03000014`; Validação: `01000006`, `01000016`, `01000026`, `01000036`, `01000046`, `01000056`, `01000066`, `01000076` |
