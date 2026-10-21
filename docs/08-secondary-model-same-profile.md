# Serving a second model inside the same profile (oMLX 0.7.2 + Sage-A1.5)

> **English** · *[Português](../pt-br/docs/08-secondary-model-same-profile.md)*

**Reference date:** October 21, 2026
**Hardware:** MacBook Pro, Apple M3 Max, 128 GB unified memory
**Baseline profile:** `~/models/qwen38-omlx` on port 8084, runtime upgraded from oMLX `0.6.3rc1` to `0.7.2`
**Secondary model:** [`InternScience/Sage-A1.5`](https://huggingface.co/InternScience/Sage-A1.5) via the oQ4e conversion `Yanun/Sage-A1.5-oQ4e-mtp`

This doc records two changes that belong together: the runtime upgrade and the addition of a second
model **as a sibling alias inside the existing profile** instead of an isolated profile like
[`06-second-local-model.md`](06-second-local-model.md). Both were executed and measured here.

---

## 1. Why same profile instead of an isolated one

Doc 06 copies the whole hardened pattern (own directory, own port, own launcher, own API key) for a
model that must never share fate with the pinned one. That is the right shape when the second model
is a permanent tenant.

Sage-A1.5 is a trial: it shares the `qwen3_5` architecture family with the pinned checkpoint, needs
the same parser/guard stack, and is meant to be compared *against* it. A sibling alias gives that
for far less surface:

| Concern | Isolated profile (doc 06) | Sibling alias (this doc) |
|---|---|---|
| Port / launcher / API key | duplicated | shared, one server |
| Cache policy, memory guard, MTP guards | duplicated, can drift | one implementation |
| Switching cost for the operator | separate URL and key | `model` field in the same request |
| Blast radius | separate process | same process — mitigated by keeping the pinned model default |

The trade-off is explicit: a bug that kills the process takes both models with it. That is why the
pinned model stays `is_default: true`, and why the validator now enforces the safety posture of both
profiles separately (§5).

## 2. Runtime upgrade

`0.7.2` is what the oQ4e conversion was produced with, so the upgrade came first.

```bash
# back up first: the venv, the pins and the validator
cd ~/models/qwen38-omlx
cp -c -R runtime/venv runtime/venv-0.6.3rc1.bak
cp PROVENANCE.txt PROVENANCE.txt.bak-0.6.3rc1
cp RUNTIME-LOCK.txt RUNTIME-LOCK.txt.bak-0.6.3rc1
cp verify-model.py verify-model.py.bak-0.6.3rc1

# install with HTTP/1.1: GitHub's HTTP/2 stream drops the mlx-vlm git fetch under load
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.version GIT_CONFIG_VALUE_0=HTTP/1.1 \
  uv pip install --python runtime/venv/bin/python \
  runtime/omlx-0.7.2-cp312-cp312-macosx_15_0_universal2.whl
```

`0.7.2` moves the MTP API. Three facade wrappers in `secure_server.py` were called with keywords
they did not accept, and failing to adapt them is a **hard decode failure**, not a slowdown:

| Upstream call | New keyword | Symptom without the fix |
|---|---|---|
| `_chain_next_drafts` | `depth` | `RuntimeError` on the first speculative cycle |
| `_post_init_mtp` | `verify_result`, `priming_offset` (kw-only) | same, during initialization |
| `_feed_next_main_to_standard` | `retain_head` | `MTP standard handoff raised` |

The fix is a passthrough on each guard, plus honouring `depth` where the upstream caller means it
(`depth=0` is the deterministic copy path, and its drafts are installed by the caller afterwards, so
the post-condition check skips that case).

## 3. Adding the alias

```bash
# checkpoint lives outside the profile; the profile only holds an alias
ln -sfn ~/Models/sage-a15-omlx/model ~/models/qwen38-omlx/models/sage-a15-omlx
```

`state/model_settings.json` gets a second block cloned from the pinned one, with identity and
sampling changed — `presence_penalty: 1.5`, `top_k: 20` and `temperature: 1.0` follow the model
card — plus `model_alias: "sage-a15-omlx"`, `is_default: false` and `model_type_override: "vlm"`
(the checkpoint ships a 27-layer vision tower).

Discovery is read at startup: the alias only appears in `/v1/models` after a restart.

## 4. Measurements

Both models resident, 39.5 GB of weights, engine ceiling 52.9 GB, zero swap.

| Probe | Result |
|---|---|
| qwen38 decode, 450 tokens | **32.7 tok/s** (was 21–22 on `0.6.3rc1`) |
| qwen38 tool call + prefix reuse | OK, `cached_tokens` populated |
| Sage text, thinking on | 100–120 tok/s |
| Sage text, thinking off | 63–86 tok/s |
| Sage factual spot check | 3/3 (arithmetic, Python one-liner, HTTP status) |
| Sage tool call | structured `tool_calls`, correct argument |
| Sage verification mode | self-review lands in `reasoning_content` |
| Sage vision (bar chart) | 5 bars, values `30, 55, 80, 45, 95`, tallest `95` |
| Sage prefix reuse, 4.2K prompt | 4 218 / 4 247 tokens, TTFT 4.10 s → 0.32 s |
| Sage MTP acceptance | 76 % at depth 1–3 |

The upgrade is not a regression for the pinned model: MTP verify sharing alone lifted long decode by
about 50 %.

## 5. Validator changes

The validator was widened, not loosened:

- model set is now exactly `{qwen38-omlx, sage-a15-omlx}`;
- context/output pins are evaluated **per model**, not once globally;
- Sage must keep the same forbidden-path posture (`turboquant_kv`, ANE prefill, specprefill,
  dflash, VLM MTP all off), MTP depth 3, `is_pinned: true`, `is_default: false` and a bounded
  thinking budget (512–8 192 tokens, currently 2 048);
- Sage shards and index are pinned by size and SHA-256 against the published `SHA256SUMS`
  (6 files) and verified on every full run.

`verify-model.py` ends green in full cryptographic mode, including the new pins.

## 6. Limits

- **The 256K context is unvalidated for this conversion.** The author of the quant says so; only
  short and 4–6K prompts were exercised here.
- **Thinking is verbose.** A trivial question can consume 1 500 reasoning tokens; without a budget
  the content comes back empty. The profile pins `thinking_budget_tokens: 2048` for this model, which
  closes the thinking block and releases content at the cap. The budget only bites when
  `max_tokens` is above it — a 300-token request still truncates first. `chat_template_kwargs:
  {"enable_thinking": false}` stays available for direct answers at 63–86 tok/s.
- **Memory is tight.** Two models plus Docker leave macOS compressing ~7.6 GB. Loading both and
  running a long prefill at once is the risky corner.
- **Community conversion.** The pinned model keeps production status; Sage is opt-in.

## 7. Rollback

```bash
cd ~/models/qwen38-omlx
./qwen-omlx stop
rm -rf runtime/venv && mv runtime/venv-0.6.3rc1.bak runtime/venv
mv PROVENANCE.txt.bak-0.6.3rc1 PROVENANCE.txt
mv RUNTIME-LOCK.txt.bak-0.6.3rc1 RUNTIME-LOCK.txt
mv verify-model.py.bak-0.6.3rc1 verify-model.py
./qwen-omlx start
```

Removing only the alias is cheaper: delete `models/sage-a15-omlx` and its `model_settings.json`
block, then restart.
