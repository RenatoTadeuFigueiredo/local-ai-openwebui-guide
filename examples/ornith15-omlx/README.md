# Ornith-1.5-9B on M3 Max — a second isolated oMLX profile

> **English** · [Português](../../pt-br/examples/ornith15-omlx/README.md)

**Reference date:** September 16, 2026  
**Measured hardware:** MacBook Pro with Apple M3 Max, 40-core GPU and 128 GB of unified memory  
**System/runtime:** macOS 15 or later, Python 3.12, oMLX `0.6.3rc1`  
**Local model:** `ornith15-omlx`  
**API:** `http://127.0.0.1:8086/v1`

This bundle installs a **second model beside the Qwen profile**, in its own directory, port and
verifier. Nothing in the existing profile changes. It is the worked answer to one question: *can a
9B model be served on this stack with the same isolation, and with Lightning MTP?* It can, with the
checkpoint below.

```text
mlx-works/Ornith-1.5-9B-oQ4e-mtp
@ f6012213916a7df42640539c1df7cd031b2569fb
```

The `mlx-works` checkpoint is a third-party quantisation of `ornith-ai/Ornith-1.5-9B`, made with the
`oQ` tool that ships with oMLX itself. It declares the base repository but **does not pin the base
revision**, so tensor-to-tensor equivalence with the official BF16 is not proven — only the chosen
revision and its files are authenticated here.

---

## 1. Why this checkpoint and not an FP8 one

FP8 is possible on this stack: MLX `0.32.1` supports `mxfp8` (group size 32, 8 bits), the `oQ` tool
emits 8-bit as `mxfp8` and ingests FP8 sources, and oMLX's Lightning MTP is not tied to a quant
format — it keys on `mtp.*` tensors, and other model families already run MTP over `oQ8e`/`mxfp8`
weights.

What does **not** exist is a published Ornith bundle with FP8 **and** a working MTP head. Every 8-bit
Ornith conversion on the Hub ships zero `mtp.*` tensors in its index:

| Bundle | Payload | `mtp.*` in index | Note |
|---|---|---|---|
| `ornith-ai/Ornith-1.5-9B-MLX-4bit` | 5.06 GB | 0 | vendor-official MLX, no MTP |
| `mlx-works/Ornith-1.5-9B-oQ4e-mtp` | 6.25 GB | **29** | oQ mixed 4/5-bit, used here |
| `djrsystemservices/Ornith-1.5-9B-oQ6e-mtp` | 8.53 GB | **29** | oQ 6-bit variant |
| `scottlowry/Ornith-1.5-9B-oQ8e` | 10.45 GB | 0 | 8-bit, no MTP |
| `OsaurusAI/Ornith-1.5-9B-MXFP8` | 10.17 GB | 0 | JANG, `bundle_has_mtp: false` |
| `Artie101/Ornith-1.5-9B-8bit-MTPLX` | 10.93 GB | 0 | MTP in a `mtp.safetensors` sidecar |

That last row matters: oMLX decides whether to attach the MTP head by reading **only**
`model.safetensors.index.json` (`omlx/utils/model_loading.py`). A head parked in a sidecar file
outside the index is invisible, so the model silently decodes without MTP.

Since the machine is memory-bandwidth bound, 8-bit also costs roughly 1.6× the bytes per token of the
oQ4e mix — before the ~30 % decode gain MTP adds on top. The oQ4e checkpoint wins on both axes; FP8
would only make sense here after quantising locally with `oQ --bits 8`, which this bundle does not do.

---

## 2. Expected result

- an oQ4e mixed-precision model (4-bit affine g64 base, 72 tensors lifted to 5-bit) with 29 embedded
  MTP tensors, ~6.2 GB of payload;
- isolated Python 3.12 venv with oMLX `0.6.3rc1`;
- Lightning MTP enabled, adaptive depth up to 3 drafts;
- native `262144`-token context, output capped at `8192`, `prompt + output <= context` enforced by the
  facade;
- single concurrency, 40 GB SSD prefix cache, private `HOME`, `HOME`-relative state;
- six inference/state routes behind Bearer, no admin/MCP/download routes;
- outbound network denied by `sandbox-exec`.

### What is not included

- re-quantisation of the BF16;
- vision. The checkpoint carries `vision_config` and processor files, but the profile forces the
  text engine (`model_type_override: llm`) exactly like the Qwen profile;
- YaRN / 1M extension;
- a hardware gate as strict as the 27B profile — a 9B fits smaller Macs, but the numbers below are
  from an M3 Max.

---

## 3. Measured results

Recorded on September 16, 2026 on the reference hardware, with the profile above. Numbers are from
this checkpoint and **must not be transferred** to the vendor's MLX conversions.

| Measurement | Result |
|---|---|
| Model load | 5.41 GB actual / 6.08 GB estimated |
| Decode with MTP, session average | 67.3 tok/s |
| MTP acceptance, short prompts | 50–60 %, depth d1–d3 |
| 109,137-token prompt, needle retrieved | yes, ~397 tok/s prefill, 275 s wall |
| 363,340-token prompt | correctly rejected: `Prompt too long … exceeds max context window of 262144` |
| Tool call through `/v1/chat/completions` | `tool_calls` returned, arguments well formed |
| Thinking separation | `reasoning_content` populated, `content` clean |
| Clean-room install of this bundle | run against a fresh target; full verifier passed |

Not measured: quality benchmarks, long-run stability, thermal behaviour, comparison against the 27B
profile.

---

## 4. Install

```bash
cd examples/ornith15-omlx
./install.sh                      # default target: ~/models/ornith15-omlx
```

The script checks macOS 15+, `python3.12`, git, free disk, that port `8086` is free and that the
LaunchAgent is not loaded; then it downloads the pinned wheel and checkpoint, builds the venv,
renders the state files, creates the model symlink and runs the **full** verifier.

```bash
./install.sh --target /Volumes/fast/models/ornith15-omlx
./install.sh --skip-download      # restore over an existing model/
```

> **Optional**. The default port is `8086` because `8085` is commonly taken by Docker on a developer
> machine (in the measured case, a Kafka Connect container). If `8086` is also busy, change `PORT` in
> `serve.sh`, `launchd-start.sh`, `ornith15-omlx` and `state/settings.json` together.

---

## 5. Verify

```bash
./runtime/venv/bin/python verify-model.py          # full: wheel + shards SHA-256, metadata identities
./runtime/venv/bin/python verify-model.py --quick  # structural only
```

The verifier pins: the oMLX wheel digest, four installed runtime versions, the checkpoint revision,
the exact file set with sizes, both shard SHA-256 values, 16 metadata Git-blob/LFS identities,
`model_type`, the 262144 native context, RoPE parameters, the 29 MTP tensors, the 72 lifted 5-bit
overrides and the quantization base. It also exercises the context/output guards and the route
allowlist, and fails closed if the sandbox, secrets or settings drift.

---

## 6. Run

```bash
./ornith15-omlx start
./ornith15-omlx status
./ornith15-omlx chat "explain the MTP head in one line"
./ornith15-omlx chat-fast "no thinking, just answer"
./ornith15-omlx stop
```

`start` runs the verifier, launches through `sandbox-exec` and waits until the model is loaded before
returning. The controller only owns processes it can prove belong to this profile.

### Autostart

```bash
sed "s#__PROFILE_ROOT__#$PWD#g" com.local.ornith-omlx.plist.template \
  > ~/Library/LaunchAgents/com.local.ornith-omlx.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.ornith-omlx.plist
```

### Long-context canary

```bash
./context-canary.py     # writes context-canary-results.json
```

---

## 7. Wiring into Open WebUI

`wire-open-webui.py` adds the connection (`http://127.0.0.1:8086/v1`, prefix `ornith`), a model row
and a wildcard read grant, so the model appears for every user. It is idempotent and needs a restart
of Open WebUI afterwards.

```bash
./wire-open-webui.py
launchctl kickstart -k gui/$(id -u)/com.local.openwebui
```

The resulting model id is `ornith.ornith15-omlx`. The script assumes the layout used by this guide
(`~/services/open-webui-mac/data/webui.db`); adjust `DB` if yours differs.

---

## 8. Honest limits

- The base revision of `ornith-ai/Ornith-1.5-9B` is not pinned by the converter; the observed value in
  the oQ calibration cache name (`3a3ef0675603`) is context, not proof.
- The converter replaced the chat template with a community "fixed" template and kept the upstream
  one as `chat_template.jinja.bak`. Templates are part of behaviour: a template change is a profile
  change.
- The sandbox is `allow default` + `deny network-outbound`: it blocks egress, not file access.
- Port, LaunchAgent label and model alias are all specific to this bundle; running two profiles that
  share a port fails fast rather than silently.
- Quality was not benchmarked. If you need a quality reference, quantise `oQ --bits 8` from the
  official BF16 yourself — and expect no MTP until you verify the head survived.