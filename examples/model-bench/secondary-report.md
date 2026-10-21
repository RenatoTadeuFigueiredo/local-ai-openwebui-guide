# Secondary-model campaign — Sage-A1.5 (`sage-a15-omlx`)

> **English** · [Português](../../pt-br/examples/model-bench/secondary-report.md)

**Reference date:** October 21, 2026
**Hardware:** MacBook Pro, Apple M3 Max, 128 GB unified memory
**Runtime:** oMLX 0.7.2, 64 GB SSD cache + 64 GB hot cache, memory guard `safe`
**Harness:** [`secondary_suite.py`](secondary_suite.py), driver [`run-secondary-campaign.sh`](run-secondary-campaign.sh)

Companion of [docs/08-secondary-model-same-profile.md](../../docs/08-secondary-model-same-profile.md).
Every number below comes from a server-side log line or the request `usage` block of that run;
raw artifacts are under `~/models/qwen38-omlx/state/benchmarks/<label>/`.

Arms are single-variable against the profile default (`vlm` engine, MTP depth 3):

| Arm | Engine | MTP |
|---|---|---|
| `sage-vlm-mtp3` | vlm (default) | depth 3 |
| `sage-llm-mtp3` | llm (text-only path) | depth 3 |
| `sage-vlm-mtp0` | vlm | off |

## Results

Decode is the median of turns 2–6, measured client-side so every arm shares one
denominator. Prefill is turn 1 (`prompt_tokens / time_to_first_token`), cold by
construction: each label gets a unique filler nonce.

| Arm | Regime | T1 prefill (tok/s) | T1 TTFT (s) | Decode (tok/s) | MTP accept |
|---|---|---|---|---|---|
| vlm + mtp3 | short (~4.6K) | 716.3 | 4.35 | **114.1** | 71.7 % |
| llm + mtp3 | short | 879.1 | 4.92 | 75.7 | 100 % |
| vlm + mtp0 | short | 876.4 | 3.68 | 93.1 | — |
| vlm + mtp3 | long (~19K) | 1061.0 | 17.45 | 81.3 | 67.3 % |
| llm + mtp3 | long | 1065.3 | 18.00 | 48.1 | 63.5 % |
| vlm + mtp0 | long | **1150.8** | **16.09** | **92.6** | — |

Factual guard (same 8 objective questions per arm): **8/8 in all three arms**.

Determinism (three identical 3-turn runs, shared filler, temperature 0): runs 2
and 3 are byte-identical; run 1 diverged at turn 1 (40/40/32 vs 31/46/58 tokens).
So determinism is **not established** for this model, unlike the pinned one.

## Reading

1. **MTP helps only while the context is short.** It lifts short decode from 93.1
   to 114.1 tok/s (+23 %) and costs 12 % at 19K (81.3 vs 92.6), where the verify
   forward runs against a much larger KV and rejection gets expensive.
2. **The text-only engine is the wrong path for this checkpoint.** `llm` loses
   ~34 % decode at short and ~41 % at long against `vlm`, with no prefill gain.
   The MoE backbone plus MTP runs better on the VLM engine even for text.
3. **Prefill is ~1 060 tok/s at 19K**, roughly 7× the pinned 27B model's 150 tok/s
   — the 1.8 B active-parameter budget shows up exactly where expected.
4. **Coexistence has a memory cost.** With both models resident the dynamic
   ceiling drops and the prefill guard rejects mid-size prompts. An interactive
   agent client made this deterministic: its ~27 K-token system prompt needed
   ~45 GB and returned 400 under the `safe` tier. Fixed by raising the tier to
   `balanced` (ceiling 45 → ~61 GB) and enabling a 600 s idle unload, which
   frees the idle model instead of pinning 17 GB. The guard stays on.

## Verdict

Keep the profile as configured (`vlm` + MTP depth 3). The pinned 27B model stays
the default; Sage is a fast opt-in. If long prompts become the main use, an
`mtp off` toggle is worth revisiting at the ~19K mark.

## Reproducing

```bash
cd examples/model-bench
./run-secondary-campaign.sh
```

`secondary_suite.py` restarts the service between arms and patches only the
selected model's `model_type_override` / `mtp_enabled`; restore the defaults
before leaving (`mtp_enabled: true`, `model_type_override: "vlm"`).
