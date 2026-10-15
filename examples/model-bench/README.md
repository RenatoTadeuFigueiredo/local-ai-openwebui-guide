# Model benchmark harness — one-variable-at-a-time config testing

> **English** · [Português](../../pt-br/examples/model-bench/README.md)

Companion of [docs/07-benchmark-prefill-kv-ane.md](../../docs/07-benchmark-prefill-kv-ane.md)
(PT-BR mirror: `pt-br/docs/07-benchmark-prefill-kv-ane.md`).

Scripts used to decide the production configuration of a local oMLX model
(Qwen3.8 27B oQ4e on M3 Max): prefix-cache mechanics, 4-bit KV quantization
(`turboquant_kv`) and Apple Neural Engine prefill (`qwen35_ane_prefill`),
each tested in isolation against a fixed baseline.

Verdict measured on this hardware: **baseline wins everywhere tested** —
fp16 KV and ANE prefill stay OFF. Full numbers in
[campaign-report.md](campaign-report.md).

## Scripts

| script | purpose |
|---|---|
| `bench_suite.py` | Full run: restart service with patched config, 6-turn conversation, collect client usage + server trace-log metrics + RSS samples |
| `regime_probe.py` | Single cold ~20K-token probe (`long`) and factual QA set (`qa`) per config |
| `reparse.py` | Rebuild a run's results from the server trace log — recovers crashed runs without GPU work |
| `analyze.py` | Cross-run performance table + output similarity vs reference |
| `template_divergence_probe.py` | Offline (tokenizer only): where `reasoning_effort`/`enable_thinking` land in the rendered prompt — proves cache-invalidation behavior without starting the server |

## Paths

All scripts assume the profile layout used by this guide's macOS deploy:
`~/models/<profile>/state/{settings.json,model_settings.json,api-key,logs/server.log}`
and the `com.local.<profile>` launchd unit. Adjust the constants at the top of
each script for your layout.

## Usage

```bash
# baseline with shared prompts (A/B identity mode)
python3 bench_suite.py --label r0s-baseline --shared-filler

# one knob at a time, same prompts
python3 bench_suite.py --label r1s-kv4 --kv4 --shared-filler
python3 bench_suite.py --label r2s-ane --ane --shared-filler

# long-context regime (cold single turn) + factual QA
python3 regime_probe.py long r3b-long-base
python3 regime_probe.py qa   qa-base

# cross-run analysis
python3 analyze.py --runs r0s-baseline r1s-kv4 r2s-ane --reference r0s-baseline

# recover a crashed run from the trace log (server clock is LOCAL time)
python3 reparse.py --label crashed-run --start 10:03:40 --end 10:07:10
```

## Method notes (read before trusting any number)

- Prove **determinism within a config first** (same request N times → byte-equal
  outputs at temperature 0). Then cross-config output divergence is real numeric
  divergence, not noise.
- Trust **server-side stamps** (`MTP path activated … primed=`, `MTP[..] finish …
  timing[...]`), cross-checked against API `usage`. Client stream timing is
  unreliable (SSE bursts).
- Validate filler generators against degeneracy (word variety, token counts) —
  a modulo bug once produced 66K tokens of one repeated word.
- Unique filler per label ⇒ cold T1; shared filler ⇒ byte-identical prompts for
  quality A/B. Do not mix modes when comparing.
- The hardening validator may pin acceleration flags; widen it before
  experimenting and re-pin the decided state afterwards.

## Requirements

Python 3.12+, `transformers` (tokenizer only) inside the model profile venv,
oMLX server running locally with trace logging during measurement
(revert `server.log_level` to `info` afterwards — trace writes full prompt
text into the log).
