# Estudo de caso: Qwen3.8-27B local no Apple M3 Max

**Período do benchmark:** 14–20 de agosto de 2026  
**Atualização operacional de 256K:** 26–27 de agosto de 2026  
**Hardware:** MacBook Pro 16", Apple M3 Max, GPU de 40 núcleos, 128 GB de memória unificada  
**Objetivo:** aumentar a geração de aproximadamente 10–15 tokens/s para perto de 50 tokens/s sem trocar por um modelo menor  
**Resultado:** aproximadamente **46,5 tokens/s de decode** e **39,2 tokens/s end-to-end** com oMLX + Lightning MTP; ganhos balanceados de **2,21×** e **1,97×** sobre o perfil llama.cpp comparado no mesmo protocolo

> **Documento histórico, não guia de instalação.** As medições oMLX deste estudo usam `pyros-vault/Qwen3.8-27B-Uncensored-oQ4e-mtp@13ec629…`. Para uma instalação nova baseada numa quantização fixada do modelo oficial, use [`../examples/qwen38-official-omlx/README.md`](../examples/qwen38-official-omlx/README.md). O checkpoint `fcmeyer/...@0299356…` é diferente; não herda automaticamente os números de 46–50 tok/s, RSS ou canários 256K registrados aqui.
>
> Este documento registra medições locais e decisões tomadas. Não é um benchmark universal. Resultados dependem de hardware, estado térmico, contexto, prompt, amostragem, quantização, runtime e versão dos kernels.

---

## 1. Resumo executivo

O ponto de partida era um Qwen3.8-27B-Uncensored `Q4_K_M` executado em `llama.cpp`/Metal. O perfil conhecido como bom já tinha várias otimizações importantes: todas as camadas na GPU, Flash Attention, KV cache Q8, lotes grandes, `mlock`, cache de prompt e MTP com profundidade 2. Em uso real, a geração variava aproximadamente entre 10 e 15 tokens/s; em ensaios curtos e aquecidos, chegou a 15–20 tokens/s.

As principais conclusões foram:

1. **O decode autorregressivo era limitado por largura de banda.** Um modelo de aproximadamente 16,8 GB precisa reler grande parte dos pesos para cada token. Os 128 GB resolvem capacidade, mas não aumentam a largura de banda de memória do M3 Max.
2. **`mlock` era essencial.** Na campanha inicial, aumentou aproximadamente 9 para 14 tokens/s — mais que qualquer truque especulativo isolado em llama.cpp.
3. **MTP no llama.cpp ajudava pouco.** `n-max=2` chegou a 15,24 tokens/s, cerca de 8% acima do plain decode; profundidades maiores pioraram.
4. **DFlash 2 não ajudou neste alvo uncensored.** O melhor braço chegou a 0,98× do plain decode e ficou abaixo do MTP.
5. **IQ4_XS economizou memória, mas não acelerou.** O resultado ajustado por ordem foi `0,999×` o Q4_K_M; portanto, manteve-se Q4_K_M.
6. **A mudança decisiva foi produzir mais de um token por leitura dos pesos com um runtime especializado.** O checkpoint oQ4e com MTP embutido, executado por oMLX/Lightning MTP, atingiu 43,1–50,6 tokens/s nos prompts medidos.
7. **O ganho final foi reproduzível.** O crossover em duas ordens mediu 46,62 e 46,39 tokens/s para o oMLX, com deriva de posição de apenas 0,5%.

### Resultado final comparável

| Métrica balanceada | llama.cpp Q4_K_M + MTP2 | oMLX oQ4e + Lightning MTP | Ganho |
|---|---:|---:|---:|
| Decode pelo relógio do cliente | ~21,1 tok/s | **~46,5 tok/s** | **2,21×** |
| End-to-end pelo relógio do cliente | ~19,9 tok/s | **~39,2 tok/s** | **1,97×** |
| Aceitação MTP | 462/590 (78,3%) | 485/594 (81,6%) | — |
| Deriva entre posições | 2,4% | 0,5% | ambos < 5% |

O pico de **50,6 tokens/s** ocorreu em continuação de código. Isso não significa 50 tokens/s sustentados em qualquer workload: a média balanceada de decode foi aproximadamente 46,5 tokens/s, e a taxa percebida end-to-end foi aproximadamente 39,2 tokens/s.

---

## 2. Como ler os números

### 2.1 Termos

- **Prefill ou prompt processing:** ingestão do prompt antes da geração.
- **Decode ou token generation:** geração dos tokens de saída.
- **TTFT:** tempo até o primeiro token.
- **End-to-end:** tokens de saída divididos pelo tempo total visto pelo cliente, incluindo prefill, fila e TTFT.
- **MTP:** Multi-Token Prediction; usa cabeças de predição do próprio modelo para propor vários tokens e verificá-los mantendo a semântica de speculative decoding.
- **Aceitação MTP:** tokens especulativos aceitos dividido por tokens propostos.

### 2.2 Campanhas não intercambiáveis

Este estudo contém quatro campanhas:

1. caracterização inicial do llama.cpp;
2. DFlash 2;
3. Q4_K_M versus IQ4_XS;
4. crossover final llama.cpp versus oMLX.

As condições não foram idênticas entre campanhas. Por exemplo, o ensaio DFlash ocorreu em bateria, com processos de desktop ativos, e apresentou números absolutos muito menores. Ele é válido para a **comparação relativa entre braços daquela campanha**, mas não deve ser usado para afirmar que o DFlash de 6,83 tok/s é diretamente comparável ao oMLX de 46,5 tok/s.

A única comparação usada para calcular o ganho final de 2,21× foi o crossover final, no qual ambos os perfis foram medidos pelo mesmo cliente, com prompts, tokens, aquecimento, contexto, cache e ordem controlados.

---

## 3. Hardware e limite físico

### 3.1 Plataforma

| Item | Valor |
|---|---|
| SoC | Apple M3 Max |
| GPU | 40 núcleos |
| Memória unificada | 128 GB |
| Largura de banda de pico | 400 GB/s |
| Runtime inicial | llama.cpp commit `7e4c0a96880dae4fc4268ad441f8a6446bd5460a`, build 200 |
| Backend | Metal + Accelerate/BLAS |
| Modelo GGUF | Qwen3.8-27B-Uncensored Q4_K_M, 27.320.697.856 parâmetros |
| Tamanho do GGUF | 16.810.714.528 bytes |

O Metal reportou que a Tensor API estava indisponível em dispositivos pré-M5/pré-A19. Logo, formatos FP8/FP4 poderiam reduzir memória, mas não obteriam uma aceleração de hardware equivalente à de chips com tensor path dedicado.

### 3.2 Por que memória livre não vira tokens/s

Com um modelo de aproximadamente 16,8 GB e largura de banda efetiva observada/esperada de aproximadamente 300–330 GB/s, o limite simplificado de uma passagem completa dos pesos é:

```text
300–330 GB/s ÷ 16,8 GB ≈ 17,9–19,6 passagens/s
```

No decode autorregressivo convencional, cada token exige aproximadamente uma nova passagem pelos pesos. Isso explica por que o llama.cpp estabilizava perto de 18–21 tokens/s em condições favoráveis.

Os 128 GB permitem:

- contextos grandes;
- caches residentes;
- ausência de pressão de capacidade;
- manter outros modelos/artefatos no disco e na memória.

Mas não aumentam os 400 GB/s do barramento. Para aproximar-se de 50 tokens/s com o mesmo 27B, seria necessário obter, em média, mais de um token validado por passagem dos pesos. Esse foi o papel do Lightning MTP.

---

## 4. Perfil inicial conhecido como bom: llama.cpp multimodal

### 4.1 Artefatos

| Componente | Local |
|---|---|
| GGUF Q4_K_M com cabeça MTP fundida | `~/models/qwen38-unc/Qwen3.8-27B-Uncensored-Q4_K_M.gguf` |
| Projetor de visão F16 | `~/models/qwen38-unc/Qwen3.8-27B-Uncensored-vision-f16.gguf` |
| Runtime llama.cpp | `~/src/llama.cpp/build/bin` |
| Controlador | `qwen` |
| Serviço | `127.0.0.1:8080` |

### 4.2 Configuração otimizada

O launcher combinava:

```text
-c 262144
--parallel 1
-ngl 99
-fa on
--cache-type-k q8_0
--cache-type-v q8_0
-b 4096
-ub 2048
--cache-reuse 256
-cram 32768
--slot-save-path ~/models/kvcache
--mlock
-t 12
--jinja
--spec-type draft-mtp
--spec-draft-n-max 2
```

Razões para cada decisão:

| Ajuste | Motivo |
|---|---|
| `--parallel 1` | um único stream recebe todo o contexto e toda a capacidade de decode |
| `-ngl 99` | todas as camadas na GPU/Metal |
| `-fa on` | Flash Attention e suporte adequado ao KV V quantizado |
| KV `q8_0` | reduz largura de banda e memória do KV com menor risco que Q4 |
| `-b 4096`, `-ub 2048` | boa ocupação dos kernels Metal no prefill |
| `--mlock` | impede que pesos sejam paginados ou relidos do file cache durante o decode |
| `-t 12` | prioriza os performance cores |
| `--jinja` | usa o template de chat do próprio modelo |
| MTP `n-max=2` | melhor ponto medido entre custo de draft e aceitação |
| `--cache-reuse`, `-cram`, slot save | reutilização de prefixos e persistência do KV |
| visão habilitada | preservava o serviço multimodal original |

### 4.3 Prefill medido

Com Q4_K_M, Flash Attention, KV Q8, `ubatch=2048`, `batch=4096` e 12 threads:

| Prompt | Prefill | Tempo aproximado | Natureza |
|---:|---:|---:|---|
| 2.048 tokens | 187,7 ± 0,5 tok/s | 11 s | medido |
| 8.192 tokens | 134,7 ± 11,7 tok/s | 61 s | medido |
| 32.768 tokens | 124,1 ± 1,4 tok/s | 4,4 min | medido |
| 65.536 tokens | ~112 tok/s | ~10 min | extrapolado |
| 131.072 tokens | ~95 tok/s | ~23 min | extrapolado |
| 262.144 tokens | ~72 tok/s | ~61 min | extrapolado |

As extrapolações foram baseadas no modelo de FLOPs calibrado com os pontos medidos, não em execuções completas desses contextos.

### 4.4 Cache de prompt

Em um prompt de 4.408 tokens:

| Estado | Tempo |
|---|---:|
| Prefixo frio | 23,82 s |
| Prefixo reutilizado | 0,19 s |
| Ganho de latência | **125×** |

Esse ganho não aumenta o decode de uma resposta já em andamento; ele elimina quase todo o custo de reprocessar prefixos idênticos em turnos posteriores.

**Ressalva posterior:** esse é um resultado histórico relatado em 14/08. Os logs multimodais preservados mais tarde avisam que `cache_reuse` não é suportado nesse caminho e foi desabilitado. Portanto, os 125× não devem ser tratados como propriedade confirmada do perfil multimodal atual; `cram`/slot cache ainda estavam configurados, mas não houve um novo A/B para isolar seu efeito efetivo.

### 4.5 Decode e profundidade de contexto

Com `mlock` e MTP `n-max=2`:

| KV ocupado | Decode | Natureza |
|---:|---:|---|
| ~0 | 15,2 tok/s | medido na campanha inicial |
| 8K | ~14,7 tok/s | extrapolado |
| 32K | ~12,2 tok/s | extrapolado a partir de medição profunda |
| 64K | ~9,7 tok/s | extrapolado |
| 128K | ~7,1 tok/s | extrapolado |
| 262K | ~4,7 tok/s | extrapolado |

O tamanho reservado por `-c` custa capacidade, mas a degradação de decode aparece principalmente à medida que o KV é efetivamente preenchido.

---

## 5. O impacto de `mlock` e MTP no llama.cpp

### 5.1 `mlock`

Na campanha inicial, a mesma configuração passou de aproximadamente:

```text
~9 tok/s sem mlock → ~14 tok/s com mlock
```

Isso representa cerca de 56% de ganho naquele ensaio. A causa observada foi evitar que os pesos mapeados fossem repetidamente atendidos pelo cache de arquivos durante o decode. Para esse perfil, `mlock` deixou de ser opcional.

### 5.2 Varredura especulativa

| Estratégia | Decode | Variação contra plain |
|---|---:|---:|
| Sem especulação, execução A | 13,92 tok/s | — |
| Sem especulação, execução B | 14,30 tok/s | — |
| MTP `n-max=2` | **15,24 tok/s** | **~+8%** |
| MTP `n-max=3` | 12,52 tok/s | ~−11% |
| `ngram-cache` | 14,87 tok/s | ~+5% |

No caminho llama.cpp testado, a cabeça MTP era executada como contexto de draft contra o alvo. Na arquitetura híbrida GatedDeltaNet, o draft tinha custo alto; a aceitação adicional em profundidades maiores não compensava esse custo. A recomendação ficou em `n-max=2`.

---

## 6. Preservação antes dos experimentos

Antes de alterar runtimes ou testar novas quantizações, foi criado um recovery point independente:

```text
~/models/qwen38-stable-2026-08-19
```

Ele contém:

- clones APFS copy-on-write dos GGUFs de texto e visão;
- executáveis e dylibs do llama.cpp congelado;
- source bundle Git e tarball do commit exato;
- scripts e configuração originais;
- `SHA256SUMS` de todos os artefatos;
- controlador separado `qwen-stable` na porta 8083.

O hash do GGUF original e do snapshot é idêntico:

```text
4c5e2db039e9325ac7724c8846c71356a24ad1cdfa28002d73ecb6be645f9675
```

O snapshot foi marcado como imutável no macOS (`uchg`) e não foi usado como diretório de experimentos.

---

## 7. Experimento DFlash 2

### 7.1 Isolamento

O DFlash foi instalado em paralelo:

| Item | Experimento |
|---|---|
| Runtime | `~/src/llama.cpp-dflash2`, commit `5ecbe1a` da PR DFlash |
| Drafter | `Qwen3.8-27B-DFlash2-Q4_K_M.gguf` |
| Controlador | `qwen-dflash` |
| Porta | 8081 |
| Target | GGUF Q4_K_M original, compartilhado como somente leitura |
| Visão | desabilitada por limitação multimodal do caminho experimental |

O drafter havia sido treinado para o alvo oficial Qwen3.8-27B; o alvo local era um derivado uncensored estruturalmente compatível. Essa diferença possivelmente reduziu a aceitação.

### 7.2 Benchmark relativo

Condições: contexto de 8K, um slot, KV Q8, Metal completo, amostragem determinística e três workloads de 64 tokens. O teste ocorreu em bateria e com processos de desktop ativos; por isso, os valores absolutos não são comparáveis às demais campanhas.

| Modo | Decode ponderado | Contra plain | Aceitação | Saída igual ao plain |
|---|---:|---:|---:|:---:|
| Plain, build estável | 6,99 tok/s | 1,00× | — | sim |
| MTP `n-max=2` | **8,35 tok/s** | **1,19×** | 81,0% | sim |
| DFlash `n-max=3` | 5,66 tok/s | 0,81× | 68,7% | sim |
| DFlash `n-max=4` | 6,40 tok/s | 0,92× | 63,8% | sim |
| DFlash `n-max=5` | **6,83 tok/s** | **0,98×** | 53,1% | sim |

**Decisão:** o DFlash funcionava, mas não era upgrade para esse checkpoint/hardware. O experimento foi mantido separado e não substituiu o perfil estável.

---

## 8. Perfil text-only e teste IQ4_XS

### 8.1 Perfil `qwen-text`

Foi criado um perfil de texto separado, na porta 8082, usando o runtime congelado e o mesmo Q4_K_M, mas sem carregar o projetor de visão. Configuração principal:

```text
-c 262144
--parallel 1
-ngl 99
-fa on
--cache-type-k q8_0
--cache-type-v q8_0
-b 4096
-ub 2048
-cram 32768
--slot-save-path ~/models/kvcache-text/Q4_K_M
--load-mode mmap+mlock
-t 12
--jinja
--spec-type draft-mtp
--spec-draft-n-max 2
```

A retirada da visão liberou aproximadamente 0,9 GB e simplificou o serviço de texto. O caminho híbrido recorrente não permitiu usar `--cache-reuse` da mesma forma; `cram` e slot save foram mantidos.

No primeiro bloco fresco, os três prompts Q4 ficaram entre **18,55 e 20,79 tok/s**. Esse intervalo não deve ser atribuído exclusivamente à remoção da visão, pois houve forte deriva térmica/de ordem nas sequências posteriores.

### 8.2 Hipótese IQ4_XS

A hipótese era que um arquivo 8,9% menor exigiria menos largura de banda:

| Quantização | Tamanho | SHA-256 |
|---|---:|---|
| Q4_K_M | 16.810.714.528 bytes | `4c5e2db...45f9675` |
| IQ4_XS | 15.309.039.008 bytes | `53adc4bb...ccc7f5` |

O IQ4_XS economizou 1.501.675.520 bytes, aproximadamente 1,40 GiB.

### 8.3 Decode nativo, sem MTP

Mesmo runtime congelado, Metal, Flash Attention, KV Q8, `mmap+mlock`, KV vazio, 128 tokens e cinco repetições:

| Quantização | Decode |
|---|---:|
| Q4_K_M | **17,80 ± 0,08 tok/s** |
| IQ4_XS | 17,57 ± 1,01 tok/s |

O IQ4_XS atingiu `0,987×` a média Q4 e teve variância maior.

### 8.4 Crossover com MTP

| Ordem | Q4_K_M | IQ4_XS | Interpretação |
|---|---:|---:|---|
| Q4 primeiro, IQ4 segundo | 19,54 tok/s | 17,71 tok/s | o segundo braço ficou mais lento |
| IQ4 primeiro, Q4 segundo | 10,71 tok/s | 11,79 tok/s | novamente o segundo braço ficou mais lento |

Estimativa multiplicativa ajustada por ordem:

```text
sqrt((17,713 / 19,540) × (11,793 / 10,707)) = 0,9992
```

| Item | Q4_K_M | IQ4_XS |
|---|---:|---:|
| Razão ajustada | 1,000× | **0,999×** |
| Aceitação MTP | 217/322 (67,4%) | 229/300 (76,3%) |
| Saídas determinísticas entre quants | diferentes | diferentes |

**Decisão:** manter Q4_K_M. O IQ4 economizava capacidade que não era necessária e seu kernel/dequantização não converteu o arquivo menor em ganho de throughput.

---

## 9. Por que migrar para MLX/oMLX

Após eliminar `mlock`, DFlash e IQ4 como caminhos para um salto de 4–5×, a análise física indicou que trocar apenas o kernel autorregressivo não seria suficiente. O requisito era validar vários tokens por leitura dos pesos.

Foi escolhido um experimento isolado com:

- oMLX `v0.6.3rc1` em ambiente Python 3.12 privado;
- MLX `0.32.0`, MLX Metal `0.32.0` e mlx-lm commit-pinned;
- checkpoint `pyros-vault/Qwen3.8-27B-Uncensored-oQ4e-mtp`;
- revisão Hugging Face `13ec62924c70a30973ea9f01094cb0a0fdc98e49`;
- quantização oQ mista, principalmente 4-bit com tensores selecionados em 5-bit;
- 16.971.681.558 bytes em quatro shards safetensors;
- 29 tensores `language_model.mtp.*`;
- Lightning MTP com profundidade adaptativa de 1 a 3.

### 9.1 Limitação de proveniência

Os dois artefatos identificam a família Qwen3.8-27B-Uncensored, mas não é possível provar que o GGUF e o MLX foram convertidos do mesmo commit BF16:

- o conversor MLX não registrou a revisão exata do source checkpoint;
- o GGUF antigo não contém repositório/commit de origem verificável.

Portanto, o crossover compara **perfis completos** — Q4_K_M/llama.cpp/MTP2 versus oQ4e/oMLX/Lightning MTP — e não dois backends sobre bytes de pesos comprovadamente idênticos.

---

## 10. Configuração final do `qwen-omlx`

### 10.1 Inferência

| Parâmetro | Valor |
|---|---|
| Engine | text-only `llm`/batched |
| Modelo | `qwen38-omlx` |
| Teto atual de admissão/posição | 262.144 tokens totais; 32.768 no A/B formal |
| Saída máxima | 8.192 tokens |
| Concorrência | 1 request |
| MTP | habilitado, até 3 draft tokens |
| Amostragem interativa | temperatura 1,0; top-p 0,95; top-k 20 |
| Benchmark | greedy, temperatura 0 |
| Cache normal | prefix/SSD isolado, máximo 40 GB desde 26/08; 20 GB no perfil benchmark original |
| Cache no A/B | desabilitado nos dois lados |
| Visão | pesos permanecem em disco, engine forçado para texto |

### 10.2 Acelerações deliberadamente desabilitadas

Para isolar a variável Lightning MTP e evitar caminhos privados ou não auditados:

- DFlash;
- TurboQuant KV;
- Qwen ANE prefill;
- speculative prefill;
- VLM MTP;
- remote model code;
- inferência distribuída.

### 10.3 Isolamento e segurança

O perfil final não usa o painel administrativo padrão do oMLX. Foi criada uma fachada ASGI mínima com apenas seis operações:

- `GET /health`;
- `GET /api/status`;
- `GET /v1/models`;
- `GET /v1/models/status`;
- `POST /v1/completions`;
- `POST /v1/chat/completions`.

Outros controles:

- bind fixo em `127.0.0.1:8084`;
- Bearer authentication obrigatória;
- sem Admin UI, OpenAPI ou docs;
- sem MCP, busca web, fetch, áudio, upload/download, quantização ou mutação de modelo;
- sem MarkItDown ou inferência distribuída;
- sandbox do macOS com `deny network-outbound`;
- `HOME` privado em `state/home`;
- segredos reais somente em arquivos owner-only, não em JSON, argumentos ou ambiente;
- wheel, versões, revisão, shards e metadados fixados; o gate `--quick` de cada start valida estrutura, tamanhos, versões e invariantes sem reler 17 GB, enquanto `qwen-omlx verify` executa a verificação criptográfica completa dos artefatos armazenados;
- `trust_remote_code=false`;
- verificador fail-closed antes do start.

O wheel oficial foi fixado por SHA-256:

```text
7010ff68df48d38f17dde034fd6f3c2dd6c6c872bed29d42513506de4734362c
```

---

## 11. Smoke test funcional do oMLX

O checkpoint carregou pelo engine text-only com 15,50 GiB de memória ativa. O runtime registrou explicitamente:

```text
Speculative backend selected ... Lightning MTP (model_type=qwen3_5, active)
```

Resultados:

| Request | Tokens | Finish | Geração do servidor | TTFT | MTP aceito | Tokens/ciclo |
|---|---:|---|---:|---:|---:|---:|
| Completion raw | 64 | length | 39,74 tok/s | 2,034 s | 37/52 (71,2%) | 2,56 |
| Chat, thinking desligado | 62 | stop | 39,37 tok/s | 0,555 s | 33/49 (67,3%) | 2,17 |

Além da resposta não vazia, o smoke exigiu no log uma ativação MTP e um resumo de ciclos para cada request. Assim, “MTP habilitado” não foi inferido apenas da configuração.

### 11.1 Ampliação operacional posterior para 256K

> Esta promoção e seus canários ocorreram somente no checkpoint uncensored `pyros-vault` implantado. O checkpoint `fcmeyer` recomendado para clean-room compartilha metadados nativos de 262144, mas precisa de inferência e canários próprios.

Em 26/08/2026, a capacidade operacional deixou de usar o cap conservador de `32768` e passou a refletir a janela nativa do checkpoint:

| Camada | Valor |
|---|---:|
| `config.json:text_config.max_position_embeddings` | `262144` |
| `tokenizer_config.json:model_max_length` | `262144` |
| fallback/policy global do oMLX | `262144` |
| override de `qwen38-omlx` | `262144` |
| `/v1/models:max_model_len` após restart | `262144` |
| máximo de saída | `8192` |
| compactação preventiva no Open WebUI | `245760` |

Os `16384` tokens entre o threshold estimado da interface e a janela total são **margem nominal**, não uma reserva rígida: até `8192` podem ser usados pela saída e o restante absorve system prompt, schemas de Tools e erro de estimativa quando couber. A fachada segura limita qualquer pedido de saída a `8192`, vincula o teto reduzido à requisição antes do streaming e garante `prompt + output <= 262144`. Como o Lightning MTP pode verificar posições que nunca chegam a ser emitidas, sua profundidade também é limitada por ciclo usando a saída restante e os offsets reais dos caches alvo e da cabeça MTP; junto ao teto, ele cai para drafts menores ou decode de um token. O cache SSD de prefixos passou de `20GB` para `40GB`, sem reservar esse volume em RAM. O memory guard `safe`, a concorrência `1` e o sandbox de rede foram preservados.

Essa mudança aumenta **capacidade**, não velocidade. O custo aparece conforme o contexto é realmente preenchido: TTFT e memória crescem, e um prefill longo monopoliza o único slot. Um gate real após o restart processou `40012` prompt tokens — acima do cap anterior — a `175,83 prompt tok/s`, com TTFT de `227,56 s`, 4 tokens gerados por streaming e contagem idêntica entre tokenizer e servidor. Um segundo gate processou `245760` prompt tokens com 1 token de saída em `2558,19 s` (~42m38s), reaproveitando `38912` tokens e reprocessando `206848`; ele comprova capacidade próxima ao threshold no estado medido, não prefill frio nem qualidade.

Depois da promoção dos guards de escopo da requisição e de fronteira do Lightning MTP, quatro canários ao vivo cobriram chat/completion raw × streaming/não streaming. Os casos `262140 + 4` e `262143 + 1` fecharam exatamente em `262144` tokens em todos os modos, embora cada chamada pedisse `8192` tokens de saída; a fachada reduziu e vinculou à requisição apenas o espaço restante. Esses canários reutilizaram `258048` ou `260096` tokens de prefixo e levaram aproximadamente 36–71 s. Portanto, provam o comportamento da borda no processo promovido, não prefill frio nem qualidade de contexto longo. Durante a campanha, o maior RSS pontual observado do processo foi aproximadamente `30,52 GiB`, a menor memória livre sistêmica reportada foi `33%`, e não houve abort do memory guard; não foi capturado trace contínuo de pico. Os benchmarks formais desta seção continuam sendo de prompts curtos com cap de 32K; não devem ser reinterpretados como benchmark de desempenho a 256K.

---

## 12. Benchmark final: llama.cpp versus oMLX

### 12.1 Objetivo

Medir os dois perfis em condições comparáveis, neutralizando:

- ordem de execução;
- aquecimento;
- cache de prefixo;
- diferenças de relógio interno dos servidores;
- EOS precoce;
- ausência silenciosa de MTP;
- processos concorrentes;
- deriva térmica/temporal.

### 12.2 Protocolo

| Item | Configuração |
|---|---|
| Hardware | mesmo M3 Max 40c/128 GB |
| Perfis | llama.cpp Q4_K_M MTP2 e oMLX oQ4e Lightning MTP |
| Context cap | 32K em ambos |
| Concorrência | 1 |
| Prompts | prosa técnica, continuação Python e artigo técnico em português |
| Saída | exatamente 128 tokens por prompt |
| Sampling | greedy, temperatura 0, seed 42 |
| Warm-up | 32 tokens idênticos por load |
| Cache | desabilitado/zero em ambos |
| Streaming | SSE em ambos |
| Métrica decode | `(N-1)/(último SSE − primeiro conteúdo SSE)` pelo mesmo cliente |
| Métrica E2E | `N/tempo total do cliente` |
| Ordens | oMLX → llama; depois llama → oMLX |
| Prompts na volta | ordem invertida |
| Cooldown | 60 s entre blocos |
| Gate MTP | draft/acceptance obrigatórios nos dois runtimes |
| Gate térmico | deriva agregada máxima de 5% |

O harness abortava se detectasse outros processos llama/oMLX, portas ocupadas, tokens insuficientes, finish diferente de `length`, cache, divergência de tokenização do prompt, ausência de MTP ou resíduos de processo ao final.

### 12.3 Todas as medições úteis

| Ordem | Backend | Prompt | Decode cliente | E2E | MTP aceito/rascunhado |
|---|---|---|---:|---:|---:|
| oMLX → llama | oMLX | prosa | 43,14 | 36,84 | 76/101 |
| oMLX → llama | oMLX | código | **50,59** | 41,98 | 85/98 |
| oMLX → llama | oMLX | português | 46,73 | 39,41 | 81/97 |
| oMLX → llama | llama.cpp | prosa | 19,96 | 18,95 | 73/106 |
| oMLX → llama | llama.cpp | código | 22,77 | 21,42 | 80/93 |
| oMLX → llama | llama.cpp | português | 21,49 | 20,31 | 78/96 |
| llama → oMLX | llama.cpp | português | 21,69 | 20,47 | 78/96 |
| llama → oMLX | llama.cpp | código | 22,42 | 21,13 | 80/93 |
| llama → oMLX | llama.cpp | prosa | 18,77 | 17,87 | 73/106 |
| llama → oMLX | oMLX | português | 45,97 | 38,51 | 82/99 |
| llama → oMLX | oMLX | código | **50,58** | 42,19 | 85/98 |
| llama → oMLX | oMLX | prosa | 43,20 | 36,98 | 76/101 |

### 12.4 Agregação por ordem

| Ordem | llama decode | oMLX decode | Razão |
|---|---:|---:|---:|
| oMLX → llama | 21,34 tok/s | 46,62 tok/s | 2,18× |
| llama → oMLX | 20,83 tok/s | 46,39 tok/s | 2,23× |
| Estimativa geométrica balanceada | — | — | **2,21×** |

| Ordem | llama E2E | oMLX E2E | Razão |
|---|---:|---:|---:|
| oMLX → llama | 20,17 tok/s | 39,30 tok/s | 1,95× |
| llama → oMLX | 19,72 tok/s | 39,11 tok/s | 1,98× |
| Estimativa geométrica balanceada | — | — | **1,97×** |

### 12.5 Estabilidade e MTP

| Item | llama.cpp | oMLX |
|---|---:|---:|
| Aceitação acumulada | 462/590 (78,3%) | 485/594 (81,6%) |
| Deriva por posição | 2,4% | 0,5% |
| Gate de estabilidade | passou | passou |

As 12 linhas foram verificadas posteriormente por um cálculo independente. Cada backend reproduziu o mesmo hash de saída por prompt entre as duas ordens; ambos reportaram a mesma quantidade de tokens de prompt; cache foi zero; todos os requests tinham evidência MTP.

### 12.6 Uso operacional posterior: saídas longas

Em 24/08/2026, logs operacionais — não um benchmark controlado — registraram duas respostas mais longas:

| Saída | Geração do servidor | Aceitação MTP | Tokens/ciclo |
|---:|---:|---:|---:|
| 2.048 tokens | 34,4 tok/s | 1.099/1.607 (68,4%) | 2,16 |
| 1.551 tokens | 37,9 tok/s | 907/1.212 (74,8%) | 2,41 |

Esses casos não preservam todo o protocolo necessário para comparação causal, mas mostram por que **46,5 tok/s não deve ser extrapolado como velocidade universal ou sustentada em respostas longas**. O perfil continuou muito acima do uso llama.cpp original, porém workload, entropia, comprimento e estado térmico mudam a aceitação e o throughput.

---

## 13. Interpretação

### 13.1 O que gerou o salto

O salto não veio de memória extra nem de uma quantização simplesmente menor. Ele veio da combinação:

1. checkpoint MLX otimizado e quantizado para o runtime;
2. cabeças MTP reais embutidas no modelo;
3. Lightning MTP com profundidade adaptativa;
4. verificação e kernels especializados em MLX/Metal;
5. um único stream, no qual os tokens aceitos amortizam leituras completas dos pesos.

A evidência prática é a média superior a dois tokens por alguns ciclos e a aceitação agregada de 81,6% no benchmark final.

### 13.2 O que não foi provado

O estudo **não prova**:

- equivalência ampla de qualidade entre oQ4e e Q4_K_M;
- identidade do checkpoint BF16 de origem;
- desempenho em 16K/32K efetivamente preenchidos;
- desempenho com várias requisições concorrentes;
- qualidade de tool use, RAG ou visão;
- 50 tokens/s sustentados em todos os prompts;
- estabilidade de longo prazo após upgrades do oMLX;
- quanto do ganho veio isoladamente do backend, da quantização ou do Lightning MTP — não houve braço oMLX com MTP desligado nem o mesmo checkpoint/quant nos dois runtimes.

Os prompts formais tinham apenas 26–29 tokens; “32K” era o teto configurado, não um contexto de 32K preenchido. As quantizações seguem trajetórias greedy diferentes. Velocidade não substitui avaliação de qualidade.

---

## 14. Decisão operacional

| Perfil | Papel |
|---|---|
| `qwen` | serviço multimodal original conhecido como bom |
| `qwen-stable` | recovery point independente e imutável |
| `qwen-text` | perfil conservador text-only em llama.cpp/Q4_K_M |
| `qwen-dflash` | pesquisa; não recomendado para uso normal |
| `qwen-omlx` | perfil de alto desempenho para texto |

Comandos do perfil rápido:

```bash
qwen-omlx start
qwen-omlx status
qwen-omlx chat "seu prompt"
qwen-omlx chat-medium "seu prompt"
qwen-omlx chat-fast "seu prompt"
qwen-omlx stop
qwen-omlx verify --quick
qwen-omlx verify
```

Nenhum alias antigo foi redirecionado. A promoção do oMLX é por comando explícito, mantendo rollback independente.

---

## 15. Próximos gates recomendados

O risco residual principal é qualidade, não velocidade. A sequência recomendada é:

1. criar uma suíte cega de 30–50 casos reais;
2. comparar `qwen-text` e `qwen-omlx` com temperatura zero;
3. executar testes de código, não apenas julgar texto;
4. cobrir português, JSON estruturado, factualidade e instruction following;
5. medir contextos efetivos de 4K, 16K e 32K;
6. observar TTFT, decode, memória e correção por 30–60 minutos;
7. somente depois criar um alias de uso diário como `qwen-fast`.

Para tarefas críticas ainda não avaliadas no oQ4e, usar `qwen-stable` ou `qwen-text`.

---

## 16. Artefatos de evidência

### Instalação e baseline

- `~/models/qwen38-unc/README-setup.md`
- `~/models/qwen38-unc/serve.sh`
- `~/models/qwen38-unc/bench.sh`

### Snapshot estável

- `~/models/qwen38-stable-2026-08-19/README.md`
- `~/models/qwen38-stable-2026-08-19/MANIFEST.txt`
- `~/models/qwen38-stable-2026-08-19/SHA256SUMS`

### DFlash

- `~/models/qwen38-dflash2/README.md`
- `~/models/qwen38-dflash2/benchmark-summary.md`
- `~/models/qwen38-dflash2/benchmark-results-quick.jsonl`

### Text-only e IQ4

- `~/models/qwen38-text/BENCHMARK-RESULTS.md`
- `~/models/qwen38-text/benchmark-quants.jsonl`
- `~/models/qwen38-text/benchmark-quants-reverse.jsonl`
- `~/models/qwen38-text/benchmark-raw-decode.jsonl`

### oMLX

- `~/models/qwen38-omlx/README.md`
- `~/models/qwen38-omlx/PROVENANCE.txt`
- `~/models/qwen38-omlx/RUNTIME-LOCK.txt`
- `~/models/qwen38-omlx/verify-model.py`
- `~/models/qwen38-omlx/smoke-summary.md`
- `~/models/qwen38-omlx/smoke-results.jsonl`
- `~/models/qwen38-omlx/benchmark-cross.py`
- `~/models/qwen38-omlx/benchmark-cross.jsonl`
- `~/models/qwen38-omlx/benchmark-cross-summary.md`
- `~/models/qwen38-omlx/context-256k-validation.json`
- `~/models/qwen38-omlx/context-256k-boundary-live-results.json`
- `~/models/qwen38-omlx/RECOMMENDATION.md`

---

## 17. Conclusão

Neste M3 Max, otimizar o caminho autorregressivo levou o Qwen3.8-27B de aproximadamente 9–18 tokens/s, conforme o estado e o protocolo, para um teto prático ao redor de 20–21 tokens/s no llama.cpp. `mlock`, Flash Attention, KV Q8, batch tuning, cache de prompt e MTP2 eram necessários, mas não suficientes para chegar a 50.

DFlash e IQ4_XS foram hipóteses razoáveis e falharam de forma mensurável. O salto real apareceu quando o sistema passou a validar múltiplos tokens por ciclo com um checkpoint e runtime desenhados para Lightning MTP. O resultado balanceado de **46,5 tokens/s de decode** — com pico reproduzido de **50,6 tokens/s** em código — representa uma melhora material sem reduzir o modelo para uma classe menor.

A conclusão correta, porém, é “maior velocidade com a mesma família 27B e quantização diferente”, e não “qualidade matematicamente idêntica”. O próximo trabalho deve ser uma avaliação de qualidade representativa e uma escada de contexto antes de declarar o oMLX substituto universal do perfil estável.
