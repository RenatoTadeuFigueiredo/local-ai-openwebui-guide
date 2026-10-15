# Production Benchmark Campaign — qwen38-omlx (Qwen3.8 27B oQ4e)

> **English** · [Português](../../pt-br/examples/model-bench/relatorio-campanha.md)

Date: 2026-09-23 · Machine: M3 Max 128 GB · Server: oMLX (trace logging on)
Harness: `state/bench_suite.py` (6-turn shared-filler runs) + `state/regime_probe.py`
(long-context & factual QA) + `state/reparse.py` / `state/analyze.py`.

## Question

Which acceleration knobs should be enabled for production use of the local
model? Candidates found in the profile, all initially pinned OFF by
`verify-model.py`: `turboquant_kv_enabled` (4-bit KV cache) and
`qwen35_ane_prefill_enabled` (Apple Neural Engine prefill). SpecPrefill and
dFlash were excluded up front (they require a separate draft model —
operational complexity out of scope).

## Method

- One variable at a time; service restarted per config.
- Shared prompts across configs (`--shared-filler`), temperature 0.
- Determinism verified first: 3 identical requests → byte-identical outputs,
  so cross-config output divergence is real numeric divergence, not noise.
- Metrics from server trace log (`primed=`, `MTP[..] finish timing[...]`),
  cross-checked against client `usage` (exact match every turn).
- Output quality: factual QA (8 questions, objective substring match) since
  text identity across configs is impossible when numerics change.

## Results

### Short-context regime (3.2K–5.8K prompt, 6-turn conversation)

| run | decode avg | accept | ΣTTFT | RSS max | QA |
|---|---|---|---|---|---|
| baseline (fp16 KV, ANE off) | **21.2 tok/s** | 71.9% | 69.2 s | 16.2 GiB | 7/8 |
| kv4 | 18.7 tok/s | 73.7% | 97.7 s | **15.9 GiB** | 7/8 |
| ane | 18.2 tok/s | 73.9% | 51.5 s * | 16.2 GiB | 7/8 |

\* T1 hit a warm 2048-token snapshot; corrected, ANE ties baseline on TTFT.

### Long-context regime (~20.4K prompt, single cold turn, 256 out)

| run | total | prefill rate | decode |
|---|---|---|---|
| baseline | **148.0 s** | **150.3 tok/s** | **21.3 tok/s** |
| kv4 | 156.8 s | 145.2 tok/s | 16.0 tok/s |
| ane | 151.6 s | 148.7 tok/s | 18.2 tok/s |

### Quality

Factual QA identical across configs (7/8 each, same question missed — a
formatting issue in the expected-answer matcher, not model knowledge).
No measurable degradation from either knob.

## Verdict

**Production config = current baseline (fp16 KV, ANE off).**

- kv4 loses ~12% decode at 3–6K and ~25% at 20K context: dequantization cost
  exceeds bandwidth savings until KV footprint is much larger than ~2 GiB.
  Only saves ~0.35 GiB RSS — not worth it even as a memory lever here.
- ANE prefill shows no measurable prefill gain at 20K (148.7 vs 150.3 tok/s)
  and slightly hurts decode.
- Both knobs remain pinned OFF in `verify-model.py` with this verdict noted.

## Cache findings (context for capacity planning)

- Prefix cache quantizes to 2048-token blocks; only complete blocks are
  stored and hits lag one turn ("storing N/… skipping trailing partial").
- Slow-growing conversations re-pay tail prefill each turn (new tokens +
  up to ~2047 alignment tokens). SSD snapshots survive restarts and match
  across conversations sharing a prefix.
- 64 GB SSD + 64 GB hot-RAM cache (set earlier today) removed the previous
  eviction pressure (was full at 39.99/40 GB).

## Operational notes for production

- Decode remains the bottleneck (~21 tok/s at chat contexts): time per
  typical 400-token reply ≈ TTFT (9–17 s) + ~19 s decode ≈ 30 s.
- Determinism holds within a config; changing numerics-changing knobs
  changes outputs (no regression detected, but A/B evals must not assume
  text identity).
- Trace logging stays ON during analysis; revert `server.log_level` to
  `info` for daily use (full prompt text lands in the log at trace).

## Artifacts

`state/benchmarks/<label>/results.json` + `server-excerpt.log` per run:
r0-baseline-v3/v4, r1-kv4, r2-ane, r0s/r1s/r2s (shared-filler triple),
r3–r5 long probes (first attempt), r3b/r4b/r5b (clean long probe),
qa-base/qa-kv4/qa-ane.
