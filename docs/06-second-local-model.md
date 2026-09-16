# Adding a second local model without touching the first

> **English** · [Português](../pt-br/docs/06-second-local-model.md)

**Reference date:** September 16, 2026  
**Status:** executed and validated end to end on the reference machine (install, full verifier, long-context canary, Open WebUI wiring); quality benchmarks and long-run/thermal behaviour not measured  
**Prerequisite:** [`02-deploy-macos-cloudflare-tunnel.md`](02-deploy-macos-cloudflare-tunnel.md) already done — the first profile is running

The first profile serves a 27B model with 256K context. This document adds a **second, smaller model
beside it**, without reconfiguring anything that already works.

The worked example is [`../examples/ornith15-omlx/`](../examples/ornith15-omlx/README.md) —
Ornith-1.5-9B, an agentic/coding 9B with native MTP, served as an isolated profile. The reasoning
applies to any other checkpoint.

---

## What "beside" means, concretely

A second profile is a copy of the same hardened pattern with its own identity. Nothing is shared:

| Resource | First profile | Second profile |
|---|---|---|
| Directory | `~/models/qwen38-omlx` | `~/models/ornith15-omlx` |
| Port | `8084` | `8086` |
| Model id | `qwen38-omlx` | `ornith15-omlx` |
| Verifier | pins the 27B checkpoint | pins the 9B checkpoint |
| LaunchAgent | `com.local.qwen-omlx` | `com.local.ornith-omlx` |
| Controller | `qwen-omlx` | `ornith15-omlx` |
| Open WebUI prefix | `local.` | `ornith.` |

The cost is disk and one more service to supervise. The benefit is that a bad checkpoint, a template
change or an oMLX regression in the second profile cannot take the first one down — and each profile
keeps its own verifier, which is what makes the guarantee checkable rather than aspirational.

> **Optional**. `8085` looks like the obvious next port and is frequently taken by Docker on a
> developer machine. Check before you commit: `lsof -nP -iTCP:8086 -sTCP:LISTEN`.

---

## Choosing the checkpoint

Three questions decide it, in this order:

1. **Does the runtime support the architecture?** oMLX `0.6.3rc1` covers the `qwen3_5` family,
   including the MTP drafter path. A model outside the supported families needs a different runtime,
   not a different profile.
2. **Does the checkpoint carry the MTP head?** MTP is what makes a small model usable at 60+ tok/s
   here. Check the index, not the model card:
   `python3 -c "import json;print(len([k for k in json.load(open('model/model.safetensors.index.json'))['weight_map'] if k.startswith('language_model.mtp.')]))"`.
   Zero means no speculative decoding, whatever the name says.
3. **Is it pinned and verifiable?** A revision you can name, a file set you can hash, a quantisation
   you can describe.

The FP8 question is a good illustration of all three: the runtime supports FP8, but no published
Ornith bundle combines FP8 with a working MTP head — and one of them hides the head in a sidecar file
that oMLX never reads. The full survey is in the [example README](../examples/ornith15-omlx/README.md).

---

## Procedure

```bash
cd examples/ornith15-omlx
./install.sh                                  # pinned wheel + pinned checkpoint + full verifier
./ornith15-omlx start                         # verifier, sandbox, wait for load
./context-canary.py                           # long-context retrieval evidence
./wire-open-webui.py                          # connection, model row, wildcard read grant
launchctl kickstart -k gui/$(id -u)/com.local.openwebui
```

Then confirm the model appears and answers through the interface — a connection that was never
exercised end to end is not a working connection.

### Measured on the reference machine

| | |
|---|---|
| Model load | 5.41 GB actual |
| Decode with MTP | 67.3 tok/s session average, 50–60 % acceptance |
| 109,137-token prompt | needle retrieved, ~397 tok/s prefill |
| Over-limit prompt (363,340 tokens) | rejected with a clear 400, not truncated silently |
| Tool calls and `reasoning_content` | both work through the facade |

---

## What this does not give you

- **Quality numbers.** Nothing here says the 9B is good, only that it runs correctly and fast.
- **A second copy of the weights.** Each profile stores its own model; there is no shared blob store.
- **Shared cache.** The SSD prefix cache is per profile, so the two do not warm each other.
- **Failover.** Both profiles are independent; neither replaces the other if one dies.

---

## Pending

- quality comparison against the 27B profile on the same prompts;
- long-run stability and thermal behaviour under sustained decoding;
- a decision on whether both profiles should autostart, or the smaller one on demand;
- vision: the checkpoint ships vision tensors, the profile forces the text engine;
- backup: the encrypted backup covers only the first profile. The second model is re-downloadable
  from a pinned revision, but its `state/` (API key, settings, per-model settings) is not backed up
  yet — a restore would regenerate the key and break the Open WebUI connection.