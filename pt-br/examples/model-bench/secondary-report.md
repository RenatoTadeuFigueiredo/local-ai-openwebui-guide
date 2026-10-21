# Campanha do modelo secundário — Sage-A1.5 (`sage-a15-omlx`)

> **Português** · [English](../../../examples/model-bench/secondary-report.md)

**Data de referência:** 21 de outubro de 2026
**Hardware:** MacBook Pro, Apple M3 Max, 128 GB de memória unificada
**Runtime:** oMLX 0.7.2, cache SSD de 64 GB + hot cache de 64 GB, memory guard `safe`
**Harness:** [`secondary_suite.py`](../../../examples/model-bench/secondary_suite.py), driver [`run-secondary-campaign.sh`](../../../examples/model-bench/run-secondary-campaign.sh)

Acompanha [docs/08-secondary-model-same-profile.md](../../docs/08-secondary-model-same-profile.md).
Todo número abaixo vem de uma linha de log do servidor ou do bloco `usage` da requisição
daquela execução; artefatos brutos ficam em `~/models/qwen38-omlx/state/benchmarks/<label>/`.

Os braços são uma variável por vez contra o padrão do perfil (engine `vlm`, MTP profundidade 3):

| Braço | Engine | MTP |
|---|---|---|
| `sage-vlm-mtp3` | vlm (padrão) | profundidade 3 |
| `sage-llm-mtp3` | llm (caminho texto) | profundidade 3 |
| `sage-vlm-mtp0` | vlm | desligado |

## Resultados

Decode é a mediana dos turnos 2–6, medida no cliente para que todos os braços
compartilhem o mesmo denominador. Prefill é o turno 1
(`prompt_tokens / time_to_first_token`), frio por construção: cada label recebe
um nonce único de filler.

| Braço | Regime | Prefill T1 (tok/s) | TTFT T1 (s) | Decode (tok/s) | Aceitação MTP |
|---|---|---|---|---|---|
| vlm + mtp3 | curto (~4,6K) | 716,3 | 4,35 | **114,1** | 71,7 % |
| llm + mtp3 | curto | 879,1 | 4,92 | 75,7 | 100 % |
| vlm + mtp0 | curto | 876,4 | 3,68 | 93,1 | — |
| vlm + mtp3 | longo (~19K) | 1061,0 | 17,45 | 81,3 | 67,3 % |
| llm + mtp3 | longo | 1065,3 | 18,00 | 48,1 | 63,5 % |
| vlm + mtp0 | longo | **1150,8** | **16,09** | **92,6** | — |

Guarda factual (mesmas 8 perguntas objetivas por braço): **8/8 nos três braços**.

Determinismo (três execuções idênticas de 3 turnos, filler compartilhado, temperatura 0):
as execuções 2 e 3 são byte-idênticas; a 1 divergiu no turno 1 (40/40/32 contra
31/46/58 tokens). Ou seja, o determinismo **não está provado** para este modelo,
ao contrário do modelo fixado.

## Leitura

1. **O MTP só ajuda com contexto curto.** Sobe o decode curto de 93,1 para 114,1
   tok/s (+23 %) e custa 12 % a 19K (81,3 contra 92,6), onde o forward de verify
   roda contra um KV muito maior e a rejeição encarece.
2. **O engine somente-texto é o caminho errado para este checkpoint.** `llm` perde
   ~34 % de decode no curto e ~41 % no longo contra `vlm`, sem ganho de prefill.
   O backbone MoE com MTP roda melhor no engine VLM até para texto.
3. **Prefill fica em ~1 060 tok/s a 19K**, cerca de 7× os 150 tok/s do modelo 27B
   fixado — o orçamento de 1,8 B parâmetros ativos aparece exatamente onde se espera.
4. **A coexistência tem custo de memória.** Com os dois modelos residentes o teto
   dinâmico cai para ~45 GB e a guarda de prefill rejeitou um prompt de 5,9K
   exigindo 40,89 GB contra 40,12 GB permitidos. É intermitente, mas é o limite
   real de rodar dois modelos ao mesmo tempo.

## Veredito

Manter o perfil como está (`vlm` + MTP profundidade 3). O modelo 27B fixado
continua o padrão; Sage é opt-in rápido. Se prompt longo virar o uso principal,
vale revisitar um toggle `mtp off` na faixa dos ~19K.

## Reproduzindo

```bash
cd examples/model-bench
./run-secondary-campaign.sh
```

O `secondary_suite.py` reinicia o serviço entre braços e altera apenas
`model_type_override` / `mtp_enabled` do modelo selecionado; restaure o padrão
antes de sair (`mtp_enabled: true`, `model_type_override: "vlm"`).
