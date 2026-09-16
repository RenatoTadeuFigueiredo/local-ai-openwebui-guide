# Case study: local Qwen3.8-27B on Apple M3 Max

> **English** · [Português](../pt-br/docs/01-case-study-qwen38-m3-max.md)

**Benchmark period:** 14–20 August 2026  
**256K operational update:** 26–27 August 2026  
**Hardware:** MacBook Pro 16", Apple M3 Max, 40-core GPU, 128 GB unified memory  
**Goal:** raise generation from approximately 10–15 tokens/s to near 50 tokens/s without switching to a smaller model  
**Result:** approximately **46,5 tokens/s decode** and **39,2 tokens/s end-to-end** with oMLX + Lightning MTP; balanced gains of **2,21×** and **1,97×** over the llama.cpp profile compared under the same protocol

> **Historical document, not an install guide.** The oMLX measurements in this study use `pyros-vault/Qwen3.8-27B-Uncensored-oQ4e-mtp@13ec629…`. For a fresh install based on a pinned quantisation of the official model, use [`../examples/qwen38-official-omlx/README.md`](../examples/qwen38-official-omlx/README.md). The `fcmeyer/...@0299356…` checkpoint is different; it does not automatically inherit the 46–50 tok/s numbers, RSS or 256K canaries recorded here.
>
> This document records local measurements and decisions taken. It is not a universal benchmark. Results depend on hardware, thermal state, context, prompt, sampling, quantisation, runtime and kernel version.

---

## 1. Executive summary

The starting point was a Qwen3.8-27B-Uncensored `Q4_K_M` running on `llama.cpp`/Metal. The profile known as good already carried several important optimisations: all layers on the GPU, Flash Attention, Q8 KV cache, large batches, `mlock`, prompt cache and MTP with depth 2. In real use, generation varied roughly between 10 and 15 tokens/s; in short, warmed-up runs it reached 15–20 tokens/s.

The main findings were:

1. **Autoregressive decode was bandwidth-bound.** A model of approximately 16,8 GB must re-read a large part of the weights for every token. The 128 GB solve capacity, but do not increase the M3 Max memory bandwidth.
2. **`mlock` was essential.** In the initial campaign it raised approximately 9 to 14 tokens/s — more than any isolated speculative trick in llama.cpp.
3. **MTP in llama.cpp helped little.** `n-max=2` reached 15,24 tokens/s, about 8% above plain decode; greater depths got worse.
4. **DFlash 2 did not help on this uncensored target.** The best arm reached 0,98× plain decode and stayed below MTP.
5. **IQ4_XS saved memory but did not speed up.** The order-adjusted result was `0,999×` Q4_K_M; therefore Q4_K_M was kept.
6. **The decisive change was producing more than one token per read of the weights with a specialised runtime.** The oQ4e checkpoint with embedded MTP, run by oMLX/Lightning MTP, reached 43,1–50,6 tokens/s on the measured prompts.
7. **The final gain was reproducible.** The two-order crossover measured 46,62 and 46,39 tokens/s for oMLX, with position drift of only 0,5%.

### Comparable final result

| Balanced metric | llama.cpp Q4_K_M + MTP2 | oMLX oQ4e + Lightning MTP | Gain |
|---|---:|---:|---:|
| Client-clock decode | ~21,1 tok/s | **~46,5 tok/s** | **2,21×** |
| Client-clock end-to-end | ~19,9 tok/s | **~39,2 tok/s** | **1,97×** |
| MTP acceptance | 462/590 (78,3%) | 485/594 (81,6%) | — |
| Drift between positions | 2,4% | 0,5% | both < 5% |

The **50,6 tokens/s** peak occurred on code continuation. That does not mean 50 sustained tokens/s on any workload: the balanced decode average was approximately 46,5 tokens/s, and the perceived end-to-end rate was approximately 39,2 tokens/s.

---

## 2. How to read the numbers

### 2.1 Terms

- **Prefill or prompt processing:** ingestion of the prompt before generation.
- **Decode or token generation:** generation of the output tokens.
- **TTFT:** time to first token.
- **End-to-end:** output tokens divided by the total time seen by the client, including prefill, queueing and TTFT.
- **MTP:** Multi-Token Prediction; uses the model's own prediction heads to propose several tokens and verify them while keeping speculative decoding semantics.
- **MTP acceptance:** speculative tokens accepted divided by tokens proposed.

### 2.2 Campaigns are not interchangeable

This study contains four campaigns:

1. initial llama.cpp characterisation;
2. DFlash 2;
3. Q4_K_M versus IQ4_XS;
4. final llama.cpp versus oMLX crossover.

Conditions were not identical across campaigns. For example, the DFlash run happened on battery, with desktop processes active, and showed much lower absolute numbers. It is valid for the **relative comparison between arms of that campaign**, but must not be used to claim that the DFlash at 6,83 tok/s is directly comparable to oMLX at 46,5 tok/s.

The only comparison used to compute the final 2,21× gain was the final crossover, in which both profiles were measured by the same client, with prompts, tokens, warm-up, context, cache and order controlled.

---

## 3. Hardware and the physical limit

### 3.1 Platform

| Item | Value |
|---|---|
| SoC | Apple M3 Max |
| GPU | 40 cores |
| Unified memory | 128 GB |
| Peak bandwidth | 400 GB/s |
| Initial runtime | llama.cpp commit `7e4c0a96880dae4fc4268ad441f8a6446bd5460a`, build 200 |
| Backend | Metal + Accelerate/BLAS |
| GGUF model | Qwen3.8-27B-Uncensored Q4_K_M, 27.320.697.856 parameters |
| GGUF size | 16.810.714.528 bytes |

Metal reported that the Tensor API was unavailable on pre-M5/pre-A19 devices. Therefore FP8/FP4 formats could reduce memory, but would not get a hardware acceleration equivalent to that of chips with a dedicated tensor path.

### 3.2 Why free memory does not become tokens/s

With a model of approximately 16,8 GB and an observed/expected effective bandwidth of approximately 300–330 GB/s, the simplified limit for one full pass over the weights is:

```text
300–330 GB/s ÷ 16,8 GB ≈ 17,9–19,6 passes/s
```

In conventional autoregressive decode, each token requires approximately one new pass over the weights. That explains why llama.cpp stabilised near 18–21 tokens/s under favourable conditions.

The 128 GB allow:

- large contexts;
- resident caches;
- no capacity pressure;
- keeping other models/artefacts on disk and in memory.

But they do not increase the 400 GB/s of the bus. To approach 50 tokens/s with the same 27B, it was necessary to obtain, on average, more than one validated token per pass over the weights. That was the role of Lightning MTP.

---

## 4. Initial profile known as good: multimodal llama.cpp

### 4.1 Artefacts

| Component | Location |
|---|---|
| Q4_K_M GGUF with fused MTP head | `~/models/qwen38-unc/Qwen3.8-27B-Uncensored-Q4_K_M.gguf` |
| F16 vision projector | `~/models/qwen38-unc/Qwen3.8-27B-Uncensored-vision-f16.gguf` |
| llama.cpp runtime | `~/src/llama.cpp/build/bin` |
| Controller | `qwen` |
| Service | `127.0.0.1:8080` |

### 4.2 Optimised configuration

The launcher combined:

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

Reasons for each decision:

| Setting | Reason |
|---|---|
| `--parallel 1` | a single stream receives the whole context and all decode capacity |
| `-ngl 99` | all layers on the GPU/Metal |
| `-fa on` | Flash Attention and proper support for quantised KV V |
| KV `q8_0` | reduces KV bandwidth and memory with less risk than Q4 |
| `-b 4096`, `-ub 2048` | good Metal kernel occupancy during prefill |
| `--mlock` | prevents weights from being paged in or re-read from the file cache during decode |
| `-t 12` | prioritises the performance cores |
| `--jinja` | uses the model's own chat template |
| MTP `n-max=2` | best measured point between draft cost and acceptance |
| `--cache-reuse`, `-cram`, slot save | prefix reuse and KV persistence |
| vision enabled | preserved the original multimodal service |

### 4.3 Measured prefill

With Q4_K_M, Flash Attention, KV Q8, `ubatch=2048`, `batch=4096` and 12 threads:

| Prompt | Prefill | Approximate time | Nature |
|---:|---:|---:|---|
| 2.048 tokens | 187,7 ± 0,5 tok/s | 11 s | measured |
| 8.192 tokens | 134,7 ± 11,7 tok/s | 61 s | measured |
| 32.768 tokens | 124,1 ± 1,4 tok/s | 4,4 min | measured |
| 65.536 tokens | ~112 tok/s | ~10 min | extrapolated |
| 131.072 tokens | ~95 tok/s | ~23 min | extrapolated |
| 262.144 tokens | ~72 tok/s | ~61 min | extrapolated |

The extrapolations were based on a FLOPs model calibrated with the measured points, not on full runs of those contexts.

### 4.4 Prompt cache

On a 4.408-token prompt:

| State | Time |
|---|---:|
| Cold prefix | 23,82 s |
| Reused prefix | 0,19 s |
| Latency gain | **125×** |

That gain does not speed up the decode of a response already in progress; it removes almost all the cost of reprocessing identical prefixes on later turns.

**Later caveat:** this is a historical result reported on 14/08. The multimodal logs preserved later warn that `cache_reuse` is not supported on that path and was disabled. Therefore the 125× must not be treated as a confirmed property of the current multimodal profile; `cram`/slot cache were still configured, but there was no new A/B to isolate their actual effect.

### 4.5 Decode and context depth

With `mlock` and MTP `n-max=2`:

| KV used | Decode | Nature |
|---:|---:|---|
| ~0 | 15,2 tok/s | measured in the initial campaign |
| 8K | ~14,7 tok/s | extrapolated |
| 32K | ~12,2 tok/s | extrapolated from a deep measurement |
| 64K | ~9,7 tok/s | extrapolated |
| 128K | ~7,1 tok/s | extrapolated |
| 262K | ~4,7 tok/s | extrapolated |

The size reserved by `-c` costs capacity, but decode degradation appears mainly as the KV is actually filled.

---

## 5. The impact of `mlock` and MTP in llama.cpp

### 5.1 `mlock`

In the initial campaign, the same configuration went from approximately:

```text
~9 tok/s without mlock → ~14 tok/s with mlock
```

That represents about a 56% gain in that run. The observed cause was preventing the mapped weights from being repeatedly served by the file cache during decode. For this profile, `mlock` stopped being optional.

### 5.2 Speculative sweep

| Strategy | Decode | Change vs plain |
|---|---:|---:|
| No speculation, run A | 13,92 tok/s | — |
| No speculation, run B | 14,30 tok/s | — |
| MTP `n-max=2` | **15,24 tok/s** | **~+8%** |
| MTP `n-max=3` | 12,52 tok/s | ~−11% |
| `ngram-cache` | 14,87 tok/s | ~+5% |

On the llama.cpp path tested, the MTP head ran as draft context against the target. In the GatedDeltaNet hybrid architecture, the draft was expensive; the extra acceptance at greater depths did not offset that cost. The recommendation settled on `n-max=2`.

---

## 6. Preservation before the experiments

Before changing runtimes or testing new quantisations, an independent recovery point was created:

```text
~/models/qwen38-stable-2026-08-19
```

It contains:

- APFS copy-on-write clones of the text and vision GGUFs;
- executables and dylibs of the frozen llama.cpp;
- Git source bundle and tarball of the exact commit;
- original scripts and configuration;
- `SHA256SUMS` of all artefacts;
- separate `qwen-stable` controller on port 8083.

The hash of the original GGUF and of the snapshot is identical:

```text
4c5e2db039e9325ac7724c8846c71356a24ad1cdfa28002d73ecb6be645f9675
```

The snapshot was marked immutable on macOS (`uchg`) and was not used as an experiments directory.

---

## 7. DFlash 2 experiment

### 7.1 Isolation

DFlash was installed in parallel:

| Item | Experiment |
|---|---|
| Runtime | `~/src/llama.cpp-dflash2`, commit `5ecbe1a` from the DFlash PR |
| Drafter | `Qwen3.8-27B-DFlash2-Q4_K_M.gguf` |
| Controller | `qwen-dflash` |
| Port | 8081 |
| Target | original Q4_K_M GGUF, shared read-only |
| Vision | disabled by a multimodal limitation of the experimental path |

The drafter had been trained for the official Qwen3.8-27B target; the local target was a structurally compatible uncensored derivative. That difference possibly reduced acceptance.

### 7.2 Relative benchmark

Conditions: 8K context, one slot, KV Q8, full Metal, deterministic sampling and three 64-token workloads. The test ran on battery and with desktop processes active; therefore the absolute values are not comparable to the other campaigns.

| Mode | Weighted decode | Vs plain | Acceptance | Output identical to plain |
|---|---:|---:|---:|:---:|
| Plain, stable build | 6,99 tok/s | 1,00× | — | yes |
| MTP `n-max=2` | **8,35 tok/s** | **1,19×** | 81,0% | yes |
| DFlash `n-max=3` | 5,66 tok/s | 0,81× | 68,7% | yes |
| DFlash `n-max=4` | 6,40 tok/s | 0,92× | 63,8% | yes |
| DFlash `n-max=5` | **6,83 tok/s** | **0,98×** | 53,1% | yes |

**Decision:** DFlash worked, but was not an upgrade for that checkpoint/hardware. The experiment was kept separate and did not replace the stable profile.

---

## 8. Text-only profile and IQ4_XS test

### 8.1 `qwen-text` profile

A separate text profile was created, on port 8082, using the frozen runtime and the same Q4_K_M, but without loading the vision projector. Main configuration:

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

Removing vision freed approximately 0,9 GB and simplified the text service. The recurrent hybrid path did not allow `--cache-reuse` to be used the same way; `cram` and slot save were kept.

In the first fresh block, the three Q4 prompts landed between **18,55 and 20,79 tok/s**. That range must not be attributed solely to removing vision, since there was strong thermal/order drift in the later sequences.

### 8.2 IQ4_XS hypothesis

The hypothesis was that an 8,9% smaller file would require less bandwidth:

| Quantisation | Size | SHA-256 |
|---|---:|---|
| Q4_K_M | 16.810.714.528 bytes | `4c5e2db...45f9675` |
| IQ4_XS | 15.309.039.008 bytes | `53adc4bb...ccc7f5` |

IQ4_XS saved 1.501.675.520 bytes, approximately 1,40 GiB.

### 8.3 Native decode, without MTP

Same frozen runtime, Metal, Flash Attention, KV Q8, `mmap+mlock`, empty KV, 128 tokens and five repetitions:

| Quantisation | Decode |
|---|---:|
| Q4_K_M | **17,80 ± 0,08 tok/s** |
| IQ4_XS | 17,57 ± 1,01 tok/s |

IQ4_XS reached `0,987×` the Q4 average and had higher variance.

### 8.4 Crossover with MTP

| Order | Q4_K_M | IQ4_XS | Interpretation |
|---|---:|---:|---|
| Q4 first, IQ4 second | 19,54 tok/s | 17,71 tok/s | the second arm was slower |
| IQ4 first, Q4 second | 10,71 tok/s | 11,79 tok/s | again the second arm was slower |

Order-adjusted multiplicative estimate:

```text
sqrt((17,713 / 19,540) × (11,793 / 10,707)) = 0,9992
```

| Item | Q4_K_M | IQ4_XS |
|---|---:|---:|
| Adjusted ratio | 1,000× | **0,999×** |
| MTP acceptance | 217/322 (67,4%) | 229/300 (76,3%) |
| Deterministic outputs across quants | different | different |

**Decision:** keep Q4_K_M. IQ4 saved capacity that was not needed and its kernel/dequantisation did not turn the smaller file into a throughput gain.

---

## 9. Why migrate to MLX/oMLX

After ruling out `mlock`, DFlash and IQ4 as paths to a 4–5× jump, the physical analysis indicated that swapping only the autoregressive kernel would not be enough. The requirement was to validate several tokens per read of the weights.

An isolated experiment was chosen with:

- oMLX `v0.6.3rc1` in a private Python 3.12 environment;
- MLX `0.32.0`, MLX Metal `0.32.0` and commit-pinned mlx-lm;
- checkpoint `pyros-vault/Qwen3.8-27B-Uncensored-oQ4e-mtp`;
- Hugging Face revision `13ec62924c70a30973ea9f01094cb0a0fdc98e49`;
- mixed oQ quantisation, mostly 4-bit with selected tensors at 5-bit;
- 16.971.681.558 bytes across four safetensors shards;
- 29 `language_model.mtp.*` tensors;
- Lightning MTP with adaptive depth from 1 to 3.

### 9.1 Provenance limitation

Both artefacts identify the Qwen3.8-27B-Uncensored family, but it is not possible to prove that the GGUF and the MLX were converted from the same BF16 commit:

- the MLX converter did not record the exact revision of the source checkpoint;
- the old GGUF contains no verifiable origin repository/commit.

Therefore the crossover compares **complete profiles** — Q4_K_M/llama.cpp/MTP2 versus oQ4e/oMLX/Lightning MTP — and not two backends over provably identical weight bytes.

---

## 10. Final configuration of `qwen-omlx`

### 10.1 Inference

| Parameter | Value |
|---|---|
| Engine | text-only `llm`/batched |
| Model | `qwen38-omlx` |
| Current admission/position ceiling | 262.144 total tokens; 32.768 in the formal A/B |
| Maximum output | 8.192 tokens |
| Concurrency | 1 request |
| MTP | enabled, up to 3 draft tokens |
| Interactive sampling | temperature 1,0; top-p 0,95; top-k 20 |
| Benchmark | greedy, temperature 0 |
| Normal cache | isolated prefix/SSD, maximum 40 GB since 26/08; 20 GB in the original benchmark profile |
| Cache in the A/B | disabled on both sides |
| Vision | weights stay on disk, engine forced to text |

### 10.2 Deliberately disabled accelerations

To isolate the Lightning MTP variable and avoid private or unaudited paths:

- DFlash;
- TurboQuant KV;
- Qwen ANE prefill;
- speculative prefill;
- VLM MTP;
- remote model code;
- distributed inference.

### 10.3 Isolation and security

The final profile does not use oMLX's default admin panel. A minimal ASGI facade was created with only six operations:

- `GET /health`;
- `GET /api/status`;
- `GET /v1/models`;
- `GET /v1/models/status`;
- `POST /v1/completions`;
- `POST /v1/chat/completions`.

Other controls:

- fixed bind on `127.0.0.1:8084`;
- mandatory Bearer authentication;
- no Admin UI, OpenAPI or docs;
- no MCP, web search, fetch, audio, upload/download, quantisation or model mutation;
- no MarkItDown or distributed inference;
- macOS sandbox with `deny network-outbound`;
- private `HOME` at `state/home`;
- real secrets only in owner-only files, not in JSON, arguments or the environment;
- wheel, versions, revision, shards and metadata pinned; the `--quick` gate of every start validates structure, sizes, versions and invariants without re-reading 17 GB, while `qwen-omlx verify` performs the full cryptographic verification of the stored artefacts;
- `trust_remote_code=false`;
- fail-closed verifier before start.

The official wheel was pinned by SHA-256:

```text
7010ff68df48d38f17dde034fd6f3c2dd6c6c872bed29d42513506de4734362c
```

---

## 11. oMLX functional smoke test

The checkpoint loaded through the text-only engine with 15,50 GiB of active memory. The runtime explicitly logged:

```text
Speculative backend selected ... Lightning MTP (model_type=qwen3_5, active)
```

Results:

| Request | Tokens | Finish | Server generation | TTFT | MTP accepted | Tokens/cycle |
|---|---:|---|---:|---:|---:|---:|
| Completion raw | 64 | length | 39,74 tok/s | 2,034 s | 37/52 (71,2%) | 2,56 |
| Chat, thinking off | 62 | stop | 39,37 tok/s | 0,555 s | 33/49 (67,3%) | 2,17 |

Beyond a non-empty response, the smoke required an MTP activation and a cycle summary in the log for each request. Thus “MTP enabled” was not inferred from configuration alone.

### 11.1 Later operational expansion to 256K

> This promotion and its canaries happened only on the deployed uncensored `pyros-vault` checkpoint. The `fcmeyer` checkpoint recommended for clean-room shares the native 262144 metadata, but needs its own inference and canaries.

On 26/08/2026, the operational capacity stopped using the conservative `32768` cap and started reflecting the checkpoint's native window:

| Layer | Value |
|---|---:|
| `config.json:text_config.max_position_embeddings` | `262144` |
| `tokenizer_config.json:model_max_length` | `262144` |
| oMLX global fallback/policy | `262144` |
| `qwen38-omlx` override | `262144` |
| `/v1/models:max_model_len` after restart | `262144` |
| maximum output | `8192` |
| preventive compaction in Open WebUI | `245760` |

The `16384` tokens between the interface's estimated threshold and the total window are **nominal margin**, not a hard reservation: up to `8192` can be used by the output and the rest absorbs system prompt, Tools schemas and estimation error when it fits. The safe facade caps any output request at `8192`, binds the reduced ceiling to the request before streaming and guarantees `prompt + output <= 262144`. Because Lightning MTP can verify positions that are never emitted, its depth is also capped per cycle using the remaining output and the real offsets of the target and MTP-head caches; next to the ceiling, it falls back to smaller drafts or single-token decode. The prefix SSD cache went from `20GB` to `40GB`, without reserving that volume in RAM. The `safe` memory guard, concurrency `1` and the network sandbox were preserved.

That change increases **capacity**, not speed. The cost appears as the context is actually filled: TTFT and memory grow, and a long prefill monopolises the single slot. A real gate after the restart processed `40012` prompt tokens — above the previous cap — at `175,83 prompt tok/s`, with a TTFT of `227,56 s`, 4 tokens generated by streaming and identical counts between tokenizer and server. A second gate processed `245760` prompt tokens with 1 output token in `2558,19 s` (~42m38s), reusing `38912` tokens and reprocessing `206848`; it proves capacity close to the threshold in the measured state, not cold prefill nor quality.

After the promotion of the request-scope and Lightning MTP boundary guards, four live canaries covered chat/raw completion × streaming/non-streaming. The `262140 + 4` and `262143 + 1` cases closed exactly at `262144` tokens in every mode, even though each call asked for `8192` output tokens; the facade reduced and bound to the request only the remaining space. Those canaries reused `258048` or `260096` prefix tokens and took approximately 36–71 s. Therefore they prove the boundary behaviour in the promoted process, not cold prefill nor long-context quality. During the campaign, the largest point-in-time RSS observed for the process was approximately `30,52 GiB`, the lowest reported system free memory was `33%`, and there was no memory guard abort; no continuous peak trace was captured. The formal benchmarks in this section remain short prompts with a 32K cap; they must not be reinterpreted as a 256K performance benchmark.

---

## 12. Final benchmark: llama.cpp versus oMLX

### 12.1 Goal

Measure both profiles under comparable conditions, neutralising:

- execution order;
- warm-up;
- prefix cache;
- differences in the servers' internal clocks;
- early EOS;
- silent absence of MTP;
- concurrent processes;
- thermal/temporal drift.

### 12.2 Protocol

| Item | Configuration |
|---|---|
| Hardware | same M3 Max 40c/128 GB |
| Profiles | llama.cpp Q4_K_M MTP2 and oMLX oQ4e Lightning MTP |
| Context cap | 32K on both |
| Concurrency | 1 |
| Prompts | technical prose, Python continuation and technical article in Portuguese |
| Output | exactly 128 tokens per prompt |
| Sampling | greedy, temperature 0, seed 42 |
| Warm-up | 32 identical tokens per load |
| Cache | disabled/zero on both |
| Streaming | SSE on both |
| Decode metric | `(N-1)/(last SSE − first SSE content)` by the same client |
| E2E metric | `N/total client time` |
| Orders | oMLX → llama; then llama → oMLX |
| Prompts on the return pass | reversed order |
| Cooldown | 60 s between blocks |
| MTP gate | draft/acceptance required in both runtimes |
| Thermal gate | maximum aggregate drift of 5% |

The harness aborted if it detected other llama/oMLX processes, occupied ports, insufficient tokens, a finish other than `length`, cache, prompt tokenisation divergence, missing MTP or process leftovers at the end.

### 12.3 All useful measurements

| Order | Backend | Prompt | Client decode | E2E | MTP accepted/drafted |
|---|---|---|---:|---:|---:|
| oMLX → llama | oMLX | prose | 43,14 | 36,84 | 76/101 |
| oMLX → llama | oMLX | code | **50,59** | 41,98 | 85/98 |
| oMLX → llama | oMLX | Portuguese | 46,73 | 39,41 | 81/97 |
| oMLX → llama | llama.cpp | prose | 19,96 | 18,95 | 73/106 |
| oMLX → llama | llama.cpp | code | 22,77 | 21,42 | 80/93 |
| oMLX → llama | llama.cpp | Portuguese | 21,49 | 20,31 | 78/96 |
| llama → oMLX | llama.cpp | Portuguese | 21,69 | 20,47 | 78/96 |
| llama → oMLX | llama.cpp | code | 22,42 | 21,13 | 80/93 |
| llama → oMLX | llama.cpp | prose | 18,77 | 17,87 | 73/106 |
| llama → oMLX | oMLX | Portuguese | 45,97 | 38,51 | 82/99 |
| llama → oMLX | oMLX | code | **50,58** | 42,19 | 85/98 |
| llama → oMLX | oMLX | prose | 43,20 | 36,98 | 76/101 |

### 12.4 Aggregation by order

| Order | llama decode | oMLX decode | Ratio |
|---|---:|---:|---:|
| oMLX → llama | 21,34 tok/s | 46,62 tok/s | 2,18× |
| llama → oMLX | 20,83 tok/s | 46,39 tok/s | 2,23× |
| Balanced geometric estimate | — | — | **2,21×** |

| Order | llama E2E | oMLX E2E | Ratio |
|---|---:|---:|---:|
| oMLX → llama | 20,17 tok/s | 39,30 tok/s | 1,95× |
| llama → oMLX | 19,72 tok/s | 39,11 tok/s | 1,98× |
| Balanced geometric estimate | — | — | **1,97×** |

### 12.5 Stability and MTP

| Item | llama.cpp | oMLX |
|---|---:|---:|
| Cumulative acceptance | 462/590 (78,3%) | 485/594 (81,6%) |
| Per-position drift | 2,4% | 0,5% |
| Stability gate | passed | passed |

The 12 rows were later verified by an independent calculation. Each backend reproduced the same output hash per prompt across both orders; both reported the same number of prompt tokens; cache was zero; every request had MTP evidence.

### 12.6 Later operational use: long outputs

On 24/08/2026, operational logs — not a controlled benchmark — recorded two longer responses:

| Output | Server generation | MTP acceptance | Tokens/cycle |
|---:|---:|---:|---:|
| 2.048 tokens | 34,4 tok/s | 1.099/1.607 (68,4%) | 2,16 |
| 1.551 tokens | 37,9 tok/s | 907/1.212 (74,8%) | 2,41 |

Those cases do not preserve the whole protocol needed for causal comparison, but they show why **46,5 tok/s must not be extrapolated as a universal or sustained speed on long responses**. The profile stayed far above the original llama.cpp usage, but workload, entropy, length and thermal state change acceptance and throughput.

---

## 13. Interpretation

### 13.1 What produced the jump

The jump did not come from extra memory nor from a simply smaller quantisation. It came from the combination:

1. an MLX checkpoint optimised and quantised for the runtime;
2. real MTP heads embedded in the model;
3. Lightning MTP with adaptive depth;
4. verification and kernels specialised in MLX/Metal;
5. a single stream, in which the accepted tokens amortise full reads of the weights.

The practical evidence is the average above two tokens for some cycles and the aggregate acceptance of 81,6% in the final benchmark.

### 13.2 What was not proved

The study **does not prove**:

- broad quality equivalence between oQ4e and Q4_K_M;
- identity of the source BF16 checkpoint;
- performance at 16K/32K actually filled;
- performance with several concurrent requests;
- quality of tool use, RAG or vision;
- 50 sustained tokens/s on every prompt;
- long-term stability after oMLX upgrades;
- how much of the gain came in isolation from the backend, the quantisation or Lightning MTP — there was no oMLX arm with MTP off nor the same checkpoint/quant on both runtimes.

The formal prompts were only 26–29 tokens; “32K” was the configured ceiling, not a filled 32K context. The quantisations follow different greedy trajectories. Speed does not replace quality evaluation.

---

## 14. Operational decision

| Profile | Role |
|---|---|
| `qwen` | original multimodal service known as good |
| `qwen-stable` | independent, immutable recovery point |
| `qwen-text` | conservative text-only profile on llama.cpp/Q4_K_M |
| `qwen-dflash` | research; not recommended for normal use |
| `qwen-omlx` | high-performance profile for text |

Fast profile commands:

```bash
qwen-omlx start
qwen-omlx status
qwen-omlx chat "your prompt"
qwen-omlx chat-medium "your prompt"
qwen-omlx chat-fast "your prompt"
qwen-omlx stop
qwen-omlx verify --quick
qwen-omlx verify
```

No old alias was redirected. oMLX promotion is by explicit command, keeping rollback independent.

---

## 15. Recommended next gates

The main residual risk is quality, not speed. The recommended sequence is:

1. create a blind suite of 30–50 real cases;
2. compare `qwen-text` and `qwen-omlx` at temperature zero;
3. run code tests, not just judge text;
4. cover Portuguese, structured JSON, factuality and instruction following;
5. measure effective 4K, 16K and 32K contexts;
6. observe TTFT, decode, memory and correctness for 30–60 minutes;
7. only then create a daily-use alias such as `qwen-fast`.

For critical tasks not yet evaluated on oQ4e, use `qwen-stable` or `qwen-text`.

---

## 16. Evidence artefacts

### Installation and baseline

- `~/models/qwen38-unc/README-setup.md`
- `~/models/qwen38-unc/serve.sh`
- `~/models/qwen38-unc/bench.sh`

### Stable snapshot

- `~/models/qwen38-stable-2026-08-19/README.md`
- `~/models/qwen38-stable-2026-08-19/MANIFEST.txt`
- `~/models/qwen38-stable-2026-08-19/SHA256SUMS`

### DFlash

- `~/models/qwen38-dflash2/README.md`
- `~/models/qwen38-dflash2/benchmark-summary.md`
- `~/models/qwen38-dflash2/benchmark-results-quick.jsonl`

### Text-only and IQ4

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

## 17. Conclusion

On this M3 Max, optimising the autoregressive path took Qwen3.8-27B from approximately 9–18 tokens/s, depending on state and protocol, to a practical ceiling around 20–21 tokens/s in llama.cpp. `mlock`, Flash Attention, KV Q8, batch tuning, prompt cache and MTP2 were necessary, but not enough to reach 50.

DFlash and IQ4_XS were reasonable hypotheses and failed measurably. The real jump appeared when the system started validating multiple tokens per cycle with a checkpoint and runtime designed for Lightning MTP. The balanced result of **46,5 tokens/s decode** — with a reproduced peak of **50,6 tokens/s** on code — represents a material improvement without dropping the model to a smaller class.

The correct conclusion, however, is “more speed with the same 27B family and a different quantisation”, and not “mathematically identical quality”. The next work should be a representative quality evaluation and a context ladder before declaring oMLX the universal replacement for the stable profile.
