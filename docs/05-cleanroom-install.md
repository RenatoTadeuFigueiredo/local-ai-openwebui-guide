# Qwen3.8-27B derived from the official: recommended clean-room path

> **English** · [Português](../pt-br/docs/05-cleanroom-install.md)

**Reference date:** August 27, 2026  
**Target hardware:** Apple M3 Max, 40-core GPU, 128 GB unified memory  
**Goal:** install a local Qwen3.8-27B with oMLX, Lightning MTP, and native 262144 context without local requantization

> The complete executable guide is in [`../examples/qwen38-official-omlx/README.md`](../examples/qwen38-official-omlx/README.md). This file is the short entry in the documentation index.

---

## Recommendation

Use the bundle [`../examples/qwen38-official-omlx/`](../examples/qwen38-official-omlx/) to download and run:

```text
fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp
@ 02993567061709709fd60b38d64819e2b8f647a3
```

This checkpoint:

- declares `Qwen/Qwen3.8-27B` as its base;
- is a community oQ4e quantization, not a checkpoint published by the Qwen team;
- keeps the native MTP head;
- takes up approximately 17 GB;
- uses an Apache-2.0 license declared on the Hub;
- is downloaded ready-made, without converting the ~56 GB of BF16 on the Mac.

The bundle pins the revision, the SHA-256 of the oMLX wheel, the hashes of the four shards, and the identities of the selected metadata; it generates local credentials and exposes only an OpenAI-compatible API on `127.0.0.1:8084`. The remaining PyPI wheels are pinned by version, but not yet by hash — see the supply chain limitation in the full guide.

---

## Minimal install

Precondition: obtain a trusted/versioned copy of the workspace. This local document still does not provide a release/commit URL or an external checksum for the bundle itself; when sharing it, publish a signed archive or an immutable commit/tag with SHA-256.

```bash
brew install python@3.12
cd examples/qwen38-official-omlx
./install.sh --target "$HOME/models/qwen38-official-omlx"
"$HOME/models/qwen38-official-omlx/qwen38-official" start
"$HOME/models/qwen38-official-omlx/qwen38-official" chat \
  "Responda somente: OK"
```

Before using 256K in clients, run the new checkpoint's own canary:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
"$PROFILE/runtime/venv/bin/python" "$PROFILE/context-canary.py" \
  --prompt-tokens 40000 --max-tokens 4 --require-mtp
```

The full procedure, including hardware, disk, verification, OpenCode, Open WebUI, LaunchAgent, context ladder, and 32768 rollback, is in the bundle README.

---

## Separation from the historical record

[`01-case-study-qwen38-m3-max.md`](01-case-study-qwen38-m3-max.md) still documents the different checkpoint:

```text
pyros-vault/Qwen3.8-27B-Uncensored-oQ4e-mtp
@ 13ec62924c70a30973ea9f01094cb0a0fdc98e49
```

Therefore, do not automatically transfer to the `fcmeyer` profile:

- average of ~46.5 tok/s or peak of ~50.6 tok/s;
- measured MTP acceptance;
- observed RSS;
- 40K/245K/boundary canaries;
- safety or quality evaluation.

The new profile must pass its own gates. 262144 metadata proves declared capacity; it does not prove long-context quality.

---

## Integrations

| Client | New identity |
|---|---|
| Controller | `qwen38-official` |
| API Model ID | `qwen38-official-omlx` |
| Directory | `~/models/qwen38-official-omlx` |
| OpenCode | `qwen38-official/qwen38-official-omlx` |
| Open WebUI with `local` prefix | `local.qwen38-official-omlx` |
| API | `http://127.0.0.1:8084/v1` |

The runbook without a VPS, [`02-deploy-macos-cloudflare-tunnel.md`](02-deploy-macos-cloudflare-tunnel.md), records the existing uncensored deployment and must not be rewritten as if the migration had already happened. The runbook with a VPS, [`03-deploy-with-vps.md`](03-deploy-with-vps.md), uses the derived official profile as the default for new deployments.
