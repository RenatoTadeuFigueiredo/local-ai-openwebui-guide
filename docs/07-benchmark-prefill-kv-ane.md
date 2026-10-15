# Benchmarking the local model for production: prefix cache, KV quantization and ANE prefill

> **English** · *[Português](../pt-br/docs/07-benchmark-prefill-kv-ane.md)*

**Reference date:** September 23, 2026
**Hardware:** MacBook Pro, Apple M3 Max (40-core GPU), 128 GB unified memory
**Model:** `qwen38-omlx` — Qwen3.8 27B oQ4e with Lightning MTP depth ≤ 3, served by oMLX on port 8084
**Question:** which acceleration knobs should be enabled before calling this stack production-ready?

This doc is the full write-up of a one-variable-at-a-time benchmark campaign.
Every number below was measured on this machine; artifacts live in
`~/models/qwen38-omlx/state/benchmarks/` (one `results.json` plus a server-log
excerpt per run) and the harness scripts are listed in §7.

---

## 1. TL;DR verdict

**Keep the baseline: fp16 KV cache and ANE prefill OFF.** Both candidate knobs lose to it:

| knob | decode @3–6K | decode @20K | RSS saved | quality |
|---|---|---|---|---|
| `turboquant_kv_enabled` (4-bit KV) | −12% | −25% | ~0.35 GiB | no regression |
| `qwen35_ane_prefill_enabled` | −10…−15% | prefill: no gain (+decode loss) | 0 | no regression |

The real production lever turned out to be **understanding the prefix cache**,
not toggling acceleration flags. And the remaining bottleneck is **decode**
(~21 tok/s at chat contexts), not prefill.

## 2. How inference time splits: prefill vs decode

Every request has two stages with opposite cost profiles:

- **Prefill** — all prompt tokens processed in parallel through every layer,
  producing one K/V pair per token per layer (the "KV cache").
  Compute-bound: measured **~100–170 tok/s** on this model across contexts
  from 2K to 66K.
- **Decode** — one token per step, reading the KV cache built so far.
  Bandwidth-bound: measured **~18–23 tok/s** regardless of context size
  between 3K and 6K (MTP speculative decoding included).

The chat API is stateless: the client re-sends the whole conversation each
turn. Whether that history is re-computed or reused is entirely up to the
server's prefix cache — hence the next section.

## 3. The prefix cache: how reuse actually works

oMLX implements a two-tier prefix cache (`BlockAwarePrefixCache` over
`PagedCacheManager`, SSD spill via `PagedSSDCacheManager`). Measured behavior:

1. **Quantization:** only complete 2048-token blocks are stored. A request
   logs `storing N/M tokens (skipping trailing partial block)` where
   `N = floor(M / 2048) * 2048`.
2. **One-turn lag:** turn *t* can only reuse what turn *t−1* stored. A slow
   conversation keeps re-paying its tail: new tokens + up to ~2047 alignment
   tokens of prefill per turn.
3. **Snapshots cover prompt + generated output**: the denominator M includes
   last turn's completion — the model's own output becomes cacheable context.
4. **Persistence:** SSD snapshots survive service restarts *and* match across
   conversations sharing a prefix. A fresh T1 opened with `cached=2048`
   because an unrelated earlier conversation had identical filler text.
5. **Cache invalidation is brutal for reasoning controls:** rendering the chat
   template with different `reasoning_effort` values shows the control tokens
   land at token ~3 of the prompt (system block). Switching effort mid-conversation
   invalidates **every** block — zero survive. Same for `enable_thinking`.
   Rule: fix the effort per conversation thread.

Measured trajectory in a growing conversation (from the paired-effort runs):
cached 0 → 2048 → 4096 → plato. The plateau was **not** a cap — it lasted
until the prompt crossed the next 2048 boundary (T6 logged
`storing 6144/7177`). With >2048 new tokens per turn the cache tracks
turn-by-turn.

### Capacity change adopted

During this campaign the profile moved from `ssd_cache_max_size: 40GB,
hot_cache_max_size: 0` to **64 GB SSD + 64 GB hot RAM cache**
(`state/settings.json`). Rationale: the 40 GB SSD tier was measured full
(39.99 GB / 196 files) — every new snapshot evicted another. With 128 GB
unified memory and a ~17.8 GiB model, the hot tier costs nothing when idle
and removes disk round-trips from repeated prefixes. The engine ceiling rose
59.9 → 66 GB accordingly. Hardening validator updated to accept both tiers.

## 4. Determinism first, then A/B

Before comparing configs we proved determinism *within* a config: three
identical requests produced byte-identical outputs (temperature 0). That
makes cross-config output divergence meaningful: it is real numeric
divergence (quantized KV / ANE precision change the logits), not noise.
Consequence: you cannot diff outputs textually across numerics-changing
knobs — use objective QA instead (§6).

All metrics were taken from the server's trace log (`MTP path activated …
primed=N`, `MTP[..] finish … timing[backbone=..ms mtp=..ms]`) and cross-checked
against the API `usage` object — they matched exactly on every turn. Client-side
stream timing proved unreliable (SSE chunks arrive burst-flushed); trust the
server stamps.

## 5. Results

### Short-context regime — 6-turn conversation, prompts 3.2K→5.8K

Shared prompts across configs (`--shared-filler`), temperature 0:

| run | decode avg | accept | ΣTTFT | RSS max |
|---|---|---|---|---|
| **baseline** (fp16 KV, ANE off) | **21.2 tok/s** | 71.9% | 69.2 s | 16.2 GiB |
| kv4 | 18.7 tok/s | 73.7% | 97.7 s | **15.9 GiB** |
| ane | 18.2 tok/s | 73.9% | 51.5 s * | 16.2 GiB |

\* first turn hit a warm 2048-token snapshot; corrected, ANE ties baseline.

### Long-context regime — single cold ~20.4K-token prompt

| run | total | prefill rate | decode |
|---|---|---|---|
| **baseline** | **148.0 s** | **150.3 tok/s** | **21.3 tok/s** |
| kv4 | 156.8 s | 145.2 tok/s | 16.0 tok/s |
| ane | 151.6 s | 148.7 tok/s | 18.2 tok/s |

### Why kv4 loses here

Dequantizing 4-bit KV inside the attention kernel costs more than the
bandwidth saves until the KV footprint is far larger than ~2 GiB. At these
context sizes the entire KV is small; the savings (~0.35 GiB RSS) never pay
for the arithmetic. Revisit only if typical contexts exceed tens of thousands
of tokens *with* long generations resident simultaneously.

### Why ANE loses here

The private ANE path routes eligible MLP work through compiled fixed-shape
programs. At 20K cold tokens it did not beat the GPU path (148.7 vs 150.3
tok/s) and slightly hurt decode. Compilation overhead + fraction routing
(0.53) apparently offset the gain on this workload shape.

### Quality guard

8 factual questions (objective substring match), same set for every config:
**7/8 each**, same question missed by all three (an answer-formatting mismatch
in the checker, not missing knowledge). No measurable degradation from either
knob — but since neither wins performance either, there is no reason to keep
them enabled.

## 6. Production numbers to expect

With the final config, a typical 400-token reply at ~3–5K context:

- TTFT ≈ 9–17 s (first turn of a session: up to ~30 s cold);
- decode ≈ 19 s;
- **total ≈ 30 s**, dominated by decode.

Repeated conversations benefit from the prefix cache: a warm follow-up turn
pays only tail prefill (~1–4 s) plus decode.

If ~21 tok/s decode is insufficient, the levers are structural, not toggles:
a separate draft model (SpecPrefill/dFlash paths exist in oMLX but need a
second checkpoint resident), more aggressive weight quantization, or larger
MTP depth. Decide based on real usage volume.

## 7. Reproducing

Harness scripts (in `~/models/qwen38-omlx/state/`):

- `bench_suite.py --label NAME [--kv4|--ane] [--shared-filler]` — restarts the
  unit with the patched config, runs a 6-turn conversation, collects client +
  server metrics + RSS samples into `state/benchmarks/NAME/`;
- `regime_probe.py long|qa NAME [--kv4|--ane]` — single cold 20K-token probe
  and the factual QA set;
- `reparse.py --label NAME --start HH:MM:SS --end HH:MM:SS` — rebuild results
  from the trace log without GPU work (recovers crashed runs);
- `analyze.py --runs ... [--reference RUN]` — cross-run table + output
  similarity;
- `template_divergence_probe.py` — offline tokenizer-only proof of where
  `reasoning_effort` lands in the rendered prompt (no server needed).

Run inventory: `r0*` baselines, `r1*/kv4`, `r2*/ane`, `r3b/r4b/r5b` long
probes, `qa-*`. Full numbers in `state/benchmarks/REPORT.md`.

## 8. Pitfalls worth remembering

1. **Filler generators must be checked for degeneracy** — the first long-context
   attempt silently produced 66K tokens of a single repeated word because a
   modulo step hit zero. Validate token counts and word variety before trusting
   a run.
2. **Warm snapshots leak across runs** if fillers collide; the shared-filler
   mode is for A/B identity checks, unique fillers for cold-T1 comparisons.
3. **Server log clock is local time**, not UTC — window filters must match or
   parses come back empty.
4. **Trace logging writes full prompt text into `state/logs/server.log`**
   (file mode 0600). Fine for analysis sessions; revert `server.log_level` to
   `info` for daily operation — done after this campaign.
5. The hardening validator (`verify-model.py`) pins acceleration flags; any
   experiment must widen the pin first, and the decided state gets re-pinned
   with the verdict as a comment.
