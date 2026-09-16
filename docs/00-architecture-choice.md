# Open WebUI: choosing between a with-VPS and a no-VPS install

> **English** · [Português](../pt-br/docs/00-architecture-choice.md)

> For the multi-user universal browser with human login, see [`04-browser-hitl-multi-user-poc.md`](04-browser-hitl-multi-user-poc.md). The published POC is a separate layer and does not change the hosting choice described below.

**Reference date:** August 27, 2026  
**Domain:** `seudominio.com`  
**Status:** architectural index; the no-VPS scenario records the current deployment, while the with-VPS scenario remains an unexecuted runbook

This file helps you choose hosting and model. The full procedures remain separate.

---

## Local model choice

For a **new reproducible install** on an M3 Max with 40 GPU cores and 128 GB, use:

- [`05-cleanroom-install.md`](05-cleanroom-install.md) — overview;
- [`../examples/qwen38-official-omlx/README.md`](../examples/qwen38-official-omlx/README.md) — executable guide and bundle.

That path downloads `fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp@0299356…`, a pinned community quantization that declares the official `Qwen/Qwen3.8-27B` model as its base. There is no local re-quantization.

The file [`01-case-study-qwen38-m3-max.md`](01-case-study-qwen38-m3-max.md) remains the **historical record** of the uncensored `pyros-vault/...` checkpoint. Its 46–50 tok/s benchmarks and 256K canaries must not be attributed to the `fcmeyer` checkpoint without a new measurement.

---

## Option 1 — no VPS

Use:

- [`02-deploy-macos-cloudflare-tunnel.md`](02-deploy-macos-cloudflare-tunnel.md)

Architecture:

```text
Phone → Cloudflare Tunnel → Open WebUI login on the Mac
                           ├→ Qwen on the Mac itself
                           └→ OpenRouter optional
```

Characteristics:

- Open WebUI runs natively on macOS;
- public WebUI at `https://chat.seudominio.com`;
- Qwen reached only via `http://127.0.0.1:8084/v1`;
- there is no `llm-home.seudominio.com`;
- no VPS and no Service Token;
- data and history stay on the Mac;
- simpler install; the login screen is public, with no Cloudflare Access/OTP, by the owner's decision;
- signup is closed and login has Cloudflare rate limiting;
- if the Mac powers off, WebUI, Qwen, and OpenRouter access through this interface go offline.

Choose this option if simplicity and local storage matter more than continuous availability.

---

## Option 2 — with VPS

Use:

- [`03-deploy-with-vps.md`](03-deploy-with-vps.md)

Architecture:

```text
                       ┌→ OpenRouter
Phone → Open WebUI VPS ┤
                       └→ Cloudflare Access/Tunnel → Qwen on the Mac
```

Characteristics:

- Open WebUI and history run on a VPS;
- public WebUI at `https://chat.seudominio.com`;
- Qwen published as a minimal API at `https://llm-home.seudominio.com/v1`;
- Cloudflare Service Auth + Qwen Bearer;
- OpenRouter stays available while the Mac is powered off;
- only the local Qwen becomes unavailable when the Mac goes down;
- more components, secrets, cost, and operational surface;
- prompts pass through the VPS/Cloudflare and history is stored on the VPS.

Choose this option if the main requirement is using the WebUI and OpenRouter even without the Mac.

---

## Direct comparison

| Criterion | No VPS | With VPS |
|---|---|---|
| WebUI when the Mac is powered off | **offline** | **online** |
| OpenRouter when the Mac is powered off | offline through that UI | **online** |
| Qwen when the Mac is powered off | offline | offline |
| History | Mac | VPS |
| Qwen API with public hostname | no | `llm-home.seudominio.com`, protected |
| Service Token | no | yes |
| Complexity | lower | higher |
| Monthly cloud compute cost | none | VPS |
| Operational privacy | data stays on the Mac; login is public | lower; the VPS sees data in cleartext |
| Backup | Mac + external copy | VPS + external storage |
| Best for | personal use tied to the Mac | continuous availability |

---

## Reserved hostnames

| Hostname | No VPS | With VPS |
|---|---|---|
| `chat.seudominio.com` | Tunnel to Open WebUI on the Mac | Tunnel to Open WebUI on the VPS |
| `llm-home.seudominio.com` | **do not create** | Tunnel to the Qwen minimal API on the Mac |
| `seudominio.com` / `www.seudominio.com` | free | free |

Do not deploy both runbooks at the same time using the same `chat.seudominio.com`: a single DNS/Tunnel route can only represent the chosen origin. To test the architectures in parallel, use distinct hostnames and separate Access applications, for example `chat-local.seudominio.com` and `chat-vps.seudominio.com`, removing them after the decision.

---

## Recommendation for the requirement already described

If you want Open WebUI to stay available with OpenRouter while the Mac is powered off, choose **with VPS**.

If you accept that everything goes offline when you power off the Mac and prefer less cost/complexity, choose **no VPS**.

**Cloudflare Tunnel does not host Open WebUI.** It carries traffic to an active origin and therefore does not change that distinction.
