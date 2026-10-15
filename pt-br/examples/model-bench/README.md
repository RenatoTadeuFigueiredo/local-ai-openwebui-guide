# Harness de benchmark de modelo — testes de config, uma variável por vez

> **Português** · [English](../../examples/model-bench/README.md)

Companheiro de [docs/07-benchmark-prefill-kv-ane.md](../../docs/07-benchmark-prefill-kv-ane.md)
(espelho EN: `docs/07-benchmark-prefill-kv-ane.md`).

Scripts usados para decidir a configuração de produção de um modelo local oMLX
(Qwen3.8 27B oQ4e no M3 Max): mecânica do cache de prefixo, quantização de KV
em 4 bits (`turboquant_kv`) e prefill na Apple Neural Engine
(`qwen35_ane_prefill`), cada um testado isoladamente contra um baseline fixo.

Veredito medido neste hardware: **o baseline vence em tudo que foi testado** —
KV fp16 e ANE prefill permanecem OFF. Números completos em
[relatorio-campanha.md](relatorio-campanha.md).

## Scripts

| script | propósito |
|---|---|
| `bench_suite.py` | Run completo: reinicia o serviço com a config alterada, conversa de 6 turnos, coleta usage do client + métricas do log trace + amostras de RSS |
| `regime_probe.py` | Probe único frio de ~20K tokens (`long`) e conjunto de QA factual (`qa`) por config |
| `reparse.py` | Reconstrói os resultados de um run a partir do log trace — recupera runs quebrados sem gastar GPU |
| `analyze.py` | Tabela cruzada de performance + similaridade de saída vs referência |
| `template_divergence_probe.py` | Offline (só tokenizer): onde `reasoning_effort`/`enable_thinking` caem no prompt renderizado — prova o comportamento de invalidação de cache sem subir o servidor |

## Caminhos

Os scripts assumem o layout de perfil usado pelo deploy macOS deste guia:
`~/models/<profile>/state/{settings.json,model_settings.json,api-key,logs/server.log}`
e a unidade launchd `com.local.<profile>`. Ajuste as constantes no topo de cada
script para o seu layout.

## Uso

```bash
# baseline com prompts compartilhados (modo identidade A/B)
python3 bench_suite.py --label r0s-baseline --shared-filler

# um knob por vez, mesmos prompts
python3 bench_suite.py --label r1s-kv4 --kv4 --shared-filler
python3 bench_suite.py --label r2s-ane --ane --shared-filler

# regime longo (turno único frio) + QA factual
python3 regime_probe.py long r3b-long-base
python3 regime_probe.py qa   qa-base

# análise cruzada
python3 analyze.py --runs r0s-baseline r1s-kv4 r2s-ane --reference r0s-baseline

# recuperar run quebrado do log trace (relógio do servidor é hora LOCAL)
python3 reparse.py --label crashed-run --start 10:03:40 --end 10:07:10
```

## Notas de método (leia antes de confiar em qualquer número)

- Prove o **determinismo dentro de uma config primeiro** (mesma request N vezes
  → byte-idêntico com temperature 0). Aí a divergência entre configs é
  divergência numérica real, não ruído.
- Confie nos **stamps do servidor** (`MTP path activated … primed=`,
  `MTP[..] finish … timing[...]`), cruzados com o `usage` da API. Timing de
  stream no cliente não é confiável (rajadas SSE).
- Valide geradores de filler contra degenerescência (variedade de palavras,
  contagem de tokens) — um bug de módulo já produziu 66K tokens de uma única
  palavra repetida.
- Filler único por label ⇒ T1 frio; filler compartilhado ⇒ prompts
  byte-idênticos para A/B de qualidade. Não misture os modos ao comparar.
- O validador de hardening pode pinar flags de aceleração; alargue antes de
  experimentar e re-pine o estado decidido depois.

## Requisitos

Python 3.12+, `transformers` (só tokenizer) no venv do perfil do modelo,
servidor oMLX rodando localmente com log trace durante a medição (reverta
`server.log_level` para `info` depois — trace grava o prompt inteiro no log).
