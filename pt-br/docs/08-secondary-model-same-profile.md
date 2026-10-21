# Servindo um segundo modelo dentro do mesmo perfil (oMLX 0.7.2 + Sage-A1.5)

> *[English](../docs/08-secondary-model-same-profile.md)* · **Português**

**Data de referência:** 21 de outubro de 2026
**Hardware:** MacBook Pro, Apple M3 Max, 128 GB de memória unificada
**Perfil base:** `~/models/qwen38-omlx` na porta 8084, runtime atualizado de oMLX `0.6.3rc1` para `0.7.2`
**Modelo secundário:** [`InternScience/Sage-A1.5`](https://huggingface.co/InternScience/Sage-A1.5) via a conversão oQ4e `Yanun/Sage-A1.5-oQ4e-mtp`

Este documento registra duas mudanças que andam juntas: a atualização de runtime e a inclusão de um
segundo modelo **como alias irmão dentro do perfil existente**, em vez de um perfil isolado como em
[`06-second-local-model.md`](06-second-local-model.md). Ambas foram executadas e medidas aqui.

---

## 1. Por que mesmo perfil, e não um isolado

O doc 06 copia todo o padrão endurecido (diretório, porta, launcher e API key próprios) para um modelo
que não deve compartilhar destino com o fixado. Essa é a forma correta quando o segundo modelo é
inquilino permanente.

Sage-A1.5 é teste: compartilha a família de arquitetura `qwen3_5` com o checkpoint fixado, precisa do
mesmo conjunto de parsers e guardas, e serve justamente para ser comparado *contra* ele. Um alias
irmão entrega isso com muito menos superfície:

| Preocupação | Perfil isolado (doc 06) | Alias irmão (este doc) |
|---|---|---|
| Porta / launcher / API key | duplicados | compartilhados, um servidor |
| Política de cache, memory guard, guardas de MTP | duplicados, sujeitos a divergir | uma implementação |
| Custo de troca para o operador | outra URL e outra chave | campo `model` na mesma requisição |
| Raio de impacto | processo separado | mesmo processo — mitigado mantendo o modelo fixado como default |

O trade-off é explícito: um bug que derruba o processo leva os dois modelos. Por isso o modelo fixado
continua `is_default: true` e o validador passou a exigir a postura de segurança dos dois perfis
separadamente (§5).

## 2. Atualização de runtime

`0.7.2` é a versão com que a conversão oQ4e foi produzida, então a atualização veio primeiro.

```bash
# backup antes: venv, pins e validador
cd ~/models/qwen38-omlx
cp -c -R runtime/venv runtime/venv-0.6.3rc1.bak
cp PROVENANCE.txt PROVENANCE.txt.bak-0.6.3rc1
cp RUNTIME-LOCK.txt RUNTIME-LOCK.txt.bak-0.6.3rc1
cp verify-model.py verify-model.py.bak-0.6.3rc1

# instale com HTTP/1.1: o HTTP/2 do GitHub derruba o fetch git do mlx-vlm sob carga
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.version GIT_CONFIG_VALUE_0=HTTP/1.1 \
  uv pip install --python runtime/venv/bin/python \
  runtime/omlx-0.7.2-cp312-cp312-macosx_15_0_universal2.whl
```

`0.7.2` muda a API de MTP. Três wrappers da fachada em `secure_server.py` passaram a ser chamados com
keywords que não aceitavam — não adaptar significa **falha dura de decode**, não lentidão:

| Chamada upstream | Keyword nova | Sintoma sem o ajuste |
|---|---|---|
| `_chain_next_drafts` | `depth` | `RuntimeError` no primeiro ciclo especulativo |
| `_post_init_mtp` | `verify_result`, `priming_offset` (kw-only) | idem, na inicialização |
| `_feed_next_main_to_standard` | `retain_head` | `MTP standard handoff raised` |

A correção é passthrough em cada guarda, mais honrar `depth` onde o chamador upstream quer dizer isso
(`depth=0` é o caminho determinístico de cópia, e os drafts são instalados pelo chamador depois — por
isso a checagem de pós-condição pula esse caso).

Nas emendas de handoff o passthrough precisa carregar o *estilo* da chamada, não só o valor: o `0.7.2`
chama `_feed_next_main_to_standard(..., retain_head=True)` por keyword, e uma guarda declarada como
`(gen_batch, state)` transforma isso em `TypeError` a cada park. Repasse `*args, **kwargs` literalmente
e encaminhe as duas formas para o helper pinado.

O booleano de retorno também não é sinônimo de sucesso. O upstream devolve `False` antes de qualquer
forward — token principal ausente, ou fila que ainda não drenou para o late join — e o chamador
responde com reconcile ou nova tentativa. Só exceção é falha de handoff, então a guarda repassa o
`False` em vez de escalá-lo. O `verify-model.py` fixa as duas metades: nenhum dos dois resultados pode
ser reescrito e uma exceção precisa virar violação.

## 3. Inclusão do alias

```bash
# o checkpoint fica fora do perfil; o perfil guarda apenas um alias
ln -sfn ~/Models/sage-a15-omlx/model ~/models/qwen38-omlx/models/sage-a15-omlx
```

`state/model_settings.json` ganha um segundo bloco clonado do fixado, com identidade e amostragem
alteradas — `presence_penalty: 1.5`, `top_k: 20` e `temperature: 1.0` seguem o model card — além de
`model_alias: "sage-a15-omlx"`, `is_default: false` e `model_type_override: "vlm"` (o checkpoint traz
uma torre de visão de 27 camadas).

O discovery é lido no boot: o alias só aparece em `/v1/models` depois de reiniciar.

## 4. Medições

Os dois modelos residentes, 39,5 GB de pesos, teto do engine 52,9 GB, swap zero.

| Sonda | Resultado |
|---|---|
| Decode qwen38, 450 tokens | **32,7 tok/s** (era 21–22 na `0.6.3rc1`) |
| Tool call + reuso de prefixo qwen38 | OK, `cached_tokens` populado |
| Texto Sage, thinking ligado | 100–120 tok/s |
| Texto Sage, thinking desligado | 63–86 tok/s |
| Checagem factual Sage | 3/3 (aritmética, one-liner Python, status HTTP) |
| Tool call Sage | `tool_calls` estruturado, argumento correto |
| Modo verificação Sage | auto-revisão cai em `reasoning_content` |
| Visão Sage (gráfico de barras) | 5 barras, valores `30, 55, 80, 45, 95`, mais alta `95` |
| Reuso de prefixo Sage, prompt 4,2K | 4 218 / 4 247 tokens, TTFT 4,10 s → 0,32 s |
| Aceitação MTP Sage | 76 % em profundidade 1–3 |

A atualização não é regressão para o modelo fixado: só o compartilhamento de verify do MTP elevou o
decode longo em cerca de 50 %.

### Campanha (braços de uma variável)

Os números de fumaça acima foram substituídos por uma campanha de verdade — mesmo
formato de harness do doc 07, braços `vlm`+MTP3 vs `llm`+MTP3 vs `vlm` sem MTP,
regimes curto (~4,6K) e longo (~19K), guarda factual de 8 perguntas, tripla de
determinismo. Decode é a mediana dos turnos 2–6.

| Braço | Decode curto | Decode longo | QA |
|---|---|---|---|
| `vlm` + MTP3 (mantido) | 114,1 tok/s | 81,3 tok/s | 8/8 |
| `llm` + MTP3 | 75,7 tok/s | 48,1 tok/s | 8/8 |
| `vlm`, MTP desligado | 93,1 tok/s | 92,6 tok/s | 8/8 |

O MTP só compensa com contexto curto; o engine somente-texto perde para `vlm` nos
dois regimes, então o perfil mantém `vlm` + MTP profundidade 3. O determinismo não
se reproduziu (2 de 3 execuções byte-idênticas). Números completos e o achado da
guarda de memória na coexistência estão em
[`../examples/model-bench/secondary-report.md`](../examples/model-bench/secondary-report.md).

## 5. Mudanças no validador

O validador foi ampliado, não afrouxado:

- o conjunto de modelos agora é exatamente `{qwen38-omlx, sage-a15-omlx}`;
- os pins de contexto e saída são avaliados **por modelo**, não uma vez no global;
- Sage precisa manter a mesma postura de caminhos proibidos (`turboquant_kv`, ANE prefill,
  specprefill, dflash, VLM MTP todos desligados), MTP profundidade 3, `is_pinned: true`,
  `is_default: false` e orçamento de thinking limitado (512–8 192 tokens, hoje 2 048);
- shards e índice de Sage são fixados por tamanho e SHA-256 contra o `SHA256SUMS` publicado
  (6 arquivos) e verificados em toda execução completa.

`verify-model.py` termina verde em modo criptográfico completo, incluindo os novos pins.

## 6. Dashboard local

O perfil ganha a própria stack LocalAgent nas portas 8791 / 9090 / 3300, com o dashboard na pasta
`LocalAgent`. Criação, portas, regras de multi-instância, verificação e as armadilhas do schema v2
estão na [doc 09](09-localagent-monitoring.md); este perfil só precisa dos dois comandos:

```bash
./monitoring/up.sh     # depois de `qwen-omlx start`
./monitoring/down.sh
```

O dashboard é genérico — descobre os modelos que a fachada serve — então `qwen38-omlx` e
`sage-a15-omlx` aparecem nos mesmos painéis sem edição por modelo. Erros de `handoff` precisam
ficar em zero; é a emenda que quebrou na adaptação ao 0.7.2.

## 7. Limites

- **O contexto de 256K não foi validado nesta conversão.** O autor do quant avisa; aqui só foram
  exercitados prompts curtos e de 4–6K.
- **O thinking é verboso.** Pergunta trivial pode consumir 1 500 tokens de raciocínio; sem orçamento
  o conteúdo volta vazio. O perfil fixa `thinking_budget_tokens: 2048` para este modelo, o que fecha
  o bloco de raciocínio e libera o conteúdo no teto. O orçamento só age quando `max_tokens` está
  acima dele — uma requisição de 300 tokens ainda trunca antes. `chat_template_kwargs:
  {"enable_thinking": false}` continua disponível para respostas diretas a 63–86 tok/s.
- **A memória fica apertada.** Dois modelos mais o Docker deixam o macOS comprimindo ~7,6 GB. Carregar
  os dois e rodar um prefill longo ao mesmo tempo é o canto arriscado.
- **Conversão comunitária.** O modelo fixado mantém o status de produção; Sage é opt-in.

### Ajuste da guarda na coexistência

Dois modelos residentes mais um system prompt de tamanho de agente não cabem no
tier `safe`. O cliente Grok Build envia ~27 K tokens de system prompt e definições
de ferramenta, o que exige ~45 GB e era recusado. Correção medida:

| Ajuste | Antes | Depois | Motivo |
|---|---|---|---|
| `memory.memory_guard_tier` | `safe` | `balanced` | teto 45 → ~61 GB, suficiente para 27 K |
| `idle_timeout.idle_timeout_seconds` | `null` | `600` | modelo sem uso descarrega em vez de segurar 17 GB |

O `prefill_memory_guard` continua ligado; o validador agora exige tier
`safe`/`balanced` e timeout entre 120 e 3600 s. O mesmo prompt de 27 K passa a
completar a 78 tok/s. O modelo padrão também está sujeito ao timeout, então voltar
depois de 10 minutos custa um carregamento (~20 s).

## 8. Rollback

```bash
cd ~/models/qwen38-omlx
./qwen-omlx stop
rm -rf runtime/venv && mv runtime/venv-0.6.3rc1.bak runtime/venv
mv PROVENANCE.txt.bak-0.6.3rc1 PROVENANCE.txt
mv RUNTIME-LOCK.txt.bak-0.6.3rc1 RUNTIME-LOCK.txt
mv verify-model.py.bak-0.6.3rc1 verify-model.py
./qwen-omlx start
```

Remover só o alias é mais barato: apague `models/sage-a15-omlx` e o bloco correspondente em
`model_settings.json`, depois reinicie.
