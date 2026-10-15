# Benchmark do modelo local para produção: cache de prefixo, KV quantizado e ANE prefill

> **Português** · *[English](../../docs/07-benchmark-prefill-kv-ane.md)*

**Data de referência:** 23 de setembro de 2026
**Hardware:** MacBook Pro, Apple M3 Max (GPU 40 núcleos), 128 GB de memória unificada
**Modelo:** `qwen38-omlx` — Qwen3.8 27B oQ4e com Lightning MTP depth ≤ 3, servido pelo oMLX na porta 8084
**Pergunta:** quais knobs de aceleração devem estar ligados antes de considerar esta stack pronta para produção?

Este doc é o relato completo de uma campanha de benchmark, uma variável por vez.
Todos os números foram medidos nesta máquina; os artefatos ficam em
`~/models/qwen38-omlx/state/benchmarks/` (um `results.json` + trecho do log do
servidor por run) e os scripts do harness estão listados na §7.

---

## 1. Veredito resumido

**Manter o baseline: KV fp16 e ANE prefill desligados.** Os dois knobs candidatos perdem:

| knob | decode @3–6K | decode @20K | RSS poupado | qualidade |
|---|---|---|---|---|
| `turboquant_kv_enabled` (KV 4-bit) | −12% | −25% | ~0,35 GiB | sem regressão |
| `qwen35_ane_prefill_enabled` | −10…−15% | prefill: sem ganho (+decode pior) | 0 | sem regressão |

A alavanca real de produção acabou sendo **entender o cache de prefixo**, não
ligar flags de aceleração. E o gargalo restante é o **decode**
(~21 tok/s em contextos de chat), não o prefill.

## 2. Como o tempo se divide: prefill vs decode

Toda requisição tem dois estágios com perfis de custo opostos:

- **Prefill** — todos os tokens do prompt processados em paralelo por todas as
  camadas, produzindo um par K/V por token por camada (o "KV cache").
  Compute-bound: medido **~100–170 tok/s** neste modelo, de contextos 2K a 66K.
- **Decode** — um token por passo, lendo o KV cache construído até ali.
  Bandwidth-bound: medido **~18–23 tok/s**, quase independente do tamanho de
  contexto entre 3K e 6K (com decodificação especulativa MTP).

A API de chat é stateless: o cliente reenvia a conversa inteira a cada turno.
Se esse histórico é recalculado ou reutilizado depende só do cache de prefixo
do servidor — daí a próxima seção.

## 3. O cache de prefixo: como o reuso funciona de verdade

O oMLX implementa cache de prefixo em duas camadas (`BlockAwarePrefixCache`
sobre `PagedCacheManager`, spill em SSD via `PagedSSDCacheManager`).
Comportamento medido:

1. **Quantização:** só blocos completos de 2048 tokens são gravados. Cada
   requisição registra `storing N/M tokens (skipping trailing partial block)`
   com `N = floor(M / 2048) * 2048`.
2. **Atraso de um turno:** o turno *t* só reutiliza o que o turno *t−1* gravou.
   Conversas que crescem devagar pagam sempre a cauda: tokens novos + até
   ~2047 tokens de alinhamento de prefill por turno.
3. **Snapshots cobrem prompt + resposta gerada**: o denominador M inclui a
   completion do último turno — a saída do próprio modelo vira contexto
   cacheável.
4. **Persistência:** snapshots em SSD sobrevivem a restarts **e** casam entre
   conversas que compartilham prefixo. Um T1 frio abriu com `cached=2048`
   porque uma conversa anterior tinha o mesmo texto-base.
5. **Invalidação brutal nos controles de raciocínio:** renderizando o chat
   template com `reasoning_effort` diferentes, os tokens de controle caem no
   token ~3 do prompt (bloco de sistema). Trocar o esforço no meio da conversa
   invalida **todos** os blocos — zero sobrevivem. O mesmo vale para
   `enable_thinking`. Regra: esforço fixo por fio de conversa.

Trajetória medida numa conversa crescente (runs pareados): cached
0 → 2048 → 4096 → platô. O platô **não era teto** — durou até o prompt cruzar a
próxima fronteira de 2048 (o T6 registrou `storing 6144/7177`). Com mais de
2048 tokens novos por turno, o cache acompanha turno a turno.

### Mudança de capacidade adotada

Durante a campanha o perfil saiu de `ssd_cache_max_size: 40GB,
hot_cache_max_size: 0` para **64 GB SSD + 64 GB hot RAM cache**
(`state/settings.json`). Justificativa: a camada SSD de 40 GB estava cheia
(39,99 GB / 196 arquivos) — cada snapshot novo expulsava outro. Com 128 GB de
memória unificada e modelo de ~17,8 GiB, a camada quente não custa nada ociosa
e tira round-trips de disco dos prefixos repetidos. O teto do engine subiu de
59,9 para 66 GB. Validador de hardening atualizado para aceitar as duas camadas.

## 4. Determinismo primeiro, A/B depois

Antes de comparar configs provamos o determinismo *dentro* de cada config: três
requisições idênticas geraram saídas byte-idênticas (temperature 0). Isso torna
a divergência entre configs significativa: é divergência numérica real (KV
quantizado / precisão ANE mudam os logits), não ruído. Consequência: não dá
para diffar texto entre knobs que mudam numeria — use QA objetivo (§6).

Todas as métricas vieram do log trace do servidor (`MTP path activated …
primed=N`, `MTP[..] finish … timing[backbone=..ms mtp=..ms]`) cruzadas com o
objeto `usage` da API — bateram exato em todos os turnos. Timing de stream no
cliente mostrou-se não-confiável (chunks SSE chegam agrupados); confie nos
stamps do servidor.

## 5. Resultados

### Regime curto — conversa de 6 turnos, prompts 3,2K→5,8K

Prompts compartilhados entre configs (`--shared-filler`), temperature 0:

| run | decode médio | accept | ΣTTFT | RSS máx |
|---|---|---|---|---|
| **baseline** (KV fp16, ANE off) | **21,2 tok/s** | 71,9% | 69,2 s | 16,2 GiB |
| kv4 | 18,7 tok/s | 73,7% | 97,7 s | **15,9 GiB** |
| ane | 18,2 tok/s | 73,9% | 51,5 s * | 16,2 GiB |

\* o T1 pegou snapshot quente de 2048 tokens; corrigido, ANE empata.

### Regime longo — um único prompt frio de ~20,4K tokens

| run | total | taxa de prefill | decode |
|---|---|---|---|
| **baseline** | **148,0 s** | **150,3 tok/s** | **21,3 tok/s** |
| kv4 | 156,8 s | 145,2 tok/s | 16,0 tok/s |
| ane | 151,6 s | 148,7 tok/s | 18,2 tok/s |

### Por que o kv4 perde aqui

Desquantizar KV de 4 bits dentro do kernel de atenção custa mais do que a
bandwidth economiza enquanto o footprint do KV for menor que vários GiB. Nesses
tamanhos de contexto o KV inteiro é pequeno; a economia (~0,35 GiB de RSS)
nunca paga a aritmética extra. Revisitar só se contextos típicos passarem de
dezenas de milhares de tokens **com** gerações longas residentes ao mesmo tempo.

### Por que o ANE perde aqui

O caminho privado da ANE roteia trabalho de MLP elegível por programas
compilados de formato fixo. Em 20K tokens frios não bateu o caminho GPU
(148,7 vs 150,3 tok/s) e piorou levemente o decode. Overhead de compilação +
roteamento por fração (0,53) aparentemente anulam o ganho nesse formato de carga.

### Guarda de qualidade

8 perguntas factuais (match exato de substring), mesmo conjunto para toda
config: **7/8 em cada**, a mesma pergunta errada pelas três (diferença de
formatação no verificador, não falta de conhecimento). Sem regressão mensurável
por nenhum knob — mas como nenhum ganha performance também, não há motivo para
mantê-los ligados.

## 6. Números de produção esperados

Com a config final, uma resposta típica de 400 tokens em contexto ~3–5K:

- TTFT ≈ 9–17 s (primeiro turno da sessão: até ~30 s frio);
- decode ≈ 19 s;
- **total ≈ 30 s**, dominado pelo decode.

Conversas repetidas aproveitam o cache de prefixo: um follow-up quente paga só
prefill de cauda (~1–4 s) + decode.

Se ~21 tok/s de decode forem insuficientes, as alavancas são estruturais, não
toggles: draft model separado (caminhos SpecPrefill/dFlash existem no oMLX mas
exigem um segundo checkpoint residente), quantização de pesos mais agressiva,
ou MTP depth maior. Decida pelo volume real de uso.

## 7. Reproduzindo

Scripts do harness (em `~/models/qwen38-omlx/state/`):

- `bench_suite.py --label NOME [--kv4|--ane] [--shared-filler]` — reinicia a
  unidade com a config alterada, roda conversa de 6 turnos, coleta métricas
  client + servidor + amostras de RSS em `state/benchmarks/NOME/`;
- `regime_probe.py long|qa NOME [--kv4|--ane]` — probe único frio de 20K tokens
  e o conjunto de QA factual;
- `reparse.py --label NOME --start HH:MM:SS --end HH:MM:SS` — reconstrói
  resultados a partir do log trace sem gastar GPU (recupera runs quebrados);
- `analyze.py --runs ... [--reference RUN]` — tabela cruzada + similaridade de
  saída;
- `template_divergence_probe.py` — prova offline (só tokenizer) de onde o
  `reasoning_effort` cai no prompt renderizado, sem servidor.

Inventário de runs: `r0*` baselines, `r1*/kv4`, `r2*/ane`, `r3b/r4b/r5b` probes
longos, `qa-*`. Números completos em `state/benchmarks/REPORT.md`.

## 8. Armadilhas que valem lembrar

1. **Geradores de filler precisam ser validados contra degenerescência** — a
   primeira tentativa longa produziu silenciosamente 66K tokens de uma única
   palavra repetida porque um passo de módulo zerou. Valide contagem de tokens
   e variedade de palavras antes de confiar no run.
2. **Snapshots quentes vazam entre runs** se os fillers colidirem; o modo
   shared-filler serve para checagens de identidade A/B, fillers únicos para
   comparações de T1 frio.
3. **O relógio do log do servidor é hora local**, não UTC — filtros de janela
   precisam casar ou o parse volta vazio.
4. **Log trace grava o prompt inteiro em `state/logs/server.log`** (modo 0600).
   Ok para sessões de análise; reverta `server.log_level` para `info` no uso
   diário — feito após esta campanha.
5. O validador de hardening (`verify-model.py`) piná as flags de aceleração;
   todo experimento precisa alargar o pin antes, e o estado decidido volta a
   ser pinado com o veredito como comentário.
