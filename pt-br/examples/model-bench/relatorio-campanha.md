# Relatório da campanha de benchmark — qwen38-omlx (Qwen3.8 27B oQ4e)

> **Português** · [English](../../../examples/model-bench/campaign-report.md)

Data: 23/09/2026 · Máquina: M3 Max 128 GB · Servidor: oMLX (log trace ativo)

## Pergunta

Quais knobs de aceleração devem estar ligados para uso em produção do modelo
local? Candidatos encontrados no perfil, todos inicialmente pinados OFF pelo
`verify-model.py`: `turboquant_kv_enabled` (KV cache 4-bit) e
`qwen35_ane_prefill_enabled` (prefill na Apple Neural Engine). SpecPrefill e
dFlash ficaram fora de escopo (exigem draft model separado — complexidade
operacional).

## Método

- Uma variável por vez; serviço reiniciado por config.
- Prompts compartilhados entre configs (`--shared-filler`), temperature 0.
- Determinismo provado antes: 3 requisições idênticas → saídas byte-idênticas,
  então divergência entre configs é divergência numérica real, não ruído.
- Métricas do log trace do servidor (`primed=`, `MTP[..] finish timing[...]`),
  cruzadas com o `usage` da API (match exato em todos os turnos).
- Qualidade: QA factual (8 perguntas, match exato de substring), já que texto
  idêntico entre configs é impossível quando a numeria muda.

## Resultados

### Regime curto (3,2K–5,8K de prompt, conversa de 6 turnos)

| run | decode médio | accept | ΣTTFT | RSS máx | QA |
|---|---|---|---|---|---|
| baseline (KV fp16, ANE off) | **21,2 tok/s** | 71,9% | 69,2 s | 16,2 GiB | 7/8 |
| kv4 | 18,7 tok/s | 73,7% | 97,7 s | **15,9 GiB** | 7/8 |
| ane | 18,2 tok/s | 73,9% | 51,5 s * | 16,2 GiB | 7/8 |

\* T1 pegou snapshot quente de 2048 tokens; corrigido, ANE empata no TTFT.

### Regime longo (~20,4K de prompt, turno único frio, 256 out)

| run | total | taxa de prefill | decode |
|---|---|---|---|
| baseline | **148,0 s** | **150,3 tok/s** | **21,3 tok/s** |
| kv4 | 156,8 s | 145,2 tok/s | 16,0 tok/s |
| ane | 151,6 s | 148,7 tok/s | 18,2 tok/s |

### Qualidade

QA factual idêntico nas três configs (7/8 cada, mesma pergunta errada —
formatação da resposta esperada no verificador, não conhecimento do modelo).
Sem regressão mensurável de nenhum knob.

## Veredito

**Config de produção = baseline atual (KV fp16, ANE off).**

- kv4 perde ~12% de decode em 3–6K e ~25% em 20K: custo de desquantização
  supera a economia de bandwidth até o KV ser muito maior que ~2 GiB. Poupa só
  ~0,35 GiB de RSS — nem como alavanca de memória vale aqui.
- ANE prefill não mostra ganho de prefill em 20K (148,7 vs 150,3 tok/s) e piora
  levemente o decode.
- Ambos permanecem pinados OFF no `verify-model.py` com este veredito anotado.

## Achados de cache (contexto para planejamento de capacidade)

- O cache de prefixo quantiza em blocos de 2048 tokens; só blocos completos são
  gravados e o hit tem atraso de um turno ("storing N/… skipping trailing
  partial").
- Conversas que crescem devagar pagam re-prefill de cauda a cada turno (tokens
  novos + até ~2047 de alinhamento). Snapshots em SSD sobrevivem a restarts e
  casam entre conversas que compartilham prefixo.
- 64 GB SSD + 64 GB hot RAM (ajustado antes desta campanha) eliminou a pressão
  de eviction anterior (estava cheio em 39,99/40 GB).

## Notas operacionais para produção

- Decode continua o gargalo (~21 tok/s em contextos de chat): resposta típica
  de 400 tokens ≈ TTFT (9–17 s) + ~19 s de decode ≈ 30 s.
- Determinismo vale dentro de uma config; knobs que mudam numeria mudam saídas
  (sem regressão detectada, mas A/B de qualidade não pode assumir identidade de
  texto).
- Log trace fica ON durante análise; reverter `server.log_level` para `info`
  no uso diário (trace grava o prompt inteiro) — feito após a campanha.

## Artefatos

`state/benchmarks/<label>/results.json` + `server-excerpt.log` por run:
r0-baseline-v3/v4, r1-kv4, r2-ane, r0s/r1s/r2s (trio shared-filler),
r3–r5 probes longos (1ª tentativa), r3b/r4b/r5b (probe longo limpo),
qa-base/qa-kv4/qa-ane.
