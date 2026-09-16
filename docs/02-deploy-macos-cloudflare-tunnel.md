# Open WebUI without a VPS: macOS, local Qwen and Cloudflare Tunnel

> **English** · [Português](../pt-br/docs/02-deploy-macos-cloudflare-tunnel.md)

**Status:** main flow deployed and approved on 25 August 2026; 256K Qwen profile promoted and validated after the final restart on 27 August 2026; physical/post-login reboot, external disaster copy, router confirmation and operational alerts still pending  
**Installed versions:** Open WebUI `v0.11.0`; Python `3.12.14`; `cloudflared` `2026.8.2`  
**Goal:** run Open WebUI directly on the Mac, reach it from the phone at `https://chat.seudominio.com` without a VPN and use `qwen38-omlx` over loopback  
**Chosen authentication:** `chat.seudominio.com` uses only the Open WebUI login/password, with no Cloudflare Access/OTP; the separate hostname `browser.seudominio.com` uses One-Time PIN exclusively for HITL takeover  
**Does not use:** VPS, Docker for the WebUI, `llm-home.seudominio.com`, Service Token or direct remote exposure of the Qwen API

> This is exclusively the **without VPS** scenario — the default for this guide. To keep the WebUI and OpenRouter available when the Mac is off, see the optional [`03-deploy-with-vps.md`](03-deploy-with-vps.md).
>
> **Provenance of the deployed state:** `qwen38-omlx` in this runbook is the uncensored checkpoint `pyros-vault/...@13ec629…`, preserved as an operational record. For another machine or a fresh install, the recommendation is the separate profile `qwen38-official-omlx`, documented in [`../examples/qwen38-official-omlx/README.md`](../examples/qwen38-official-omlx/README.md). Do not swap IDs/paths in this document without running and dating a real migration.

## Conventions: substitute your own values

The documents describe one concrete deployment. The identifiers below are **placeholders** — replace them with your own:

| Placeholder | What it is |
|---|---|
| `seudominio.com` | Your own domain. All subdomains derive from it: `chat.`, `browser.`, `llm-home.` |
| `admin` | The machine operator — you. Installs, has root-equivalent access and sees the private models |
| `user-a`, `user-b` | Other users with access. Have their own login, isolated browser profile and no administrative privilege |
| `user-c`, `user-d` | Planned users, no optional container yet |
| `cptr/admin` | Private model ID, in the `prefix/name` format Open WebUI uses |

None of this is configuration to copy literally: when following the guide, generate your own secrets, choose your own domain and create your own accounts.

---

## 1. Architectural guarantee and availability

Cloudflare Tunnel publishes a process that keeps running on the Mac; it does not host that process on Cloudflare.

```text
Phone
  │ HTTPS + Cloudflare proxy
  ▼
Cloudflare Tunnel
  │
  ▼
Open WebUI native login 127.0.0.1:3000 on the Mac
  ├── HTTP loopback + Bearer ──→ qwen-omlx 127.0.0.1:8084
  └── optional HTTPS ──────────→ OpenRouter
```

### When the Mac is off

| Component | Availability |
|---|:---:|
| `https://chat.seudominio.com` | no |
| Open WebUI interface and history | no |
| Local Qwen | not remotely |
| OpenRouter through this interface | no |
| Local data on disk | preserved |

Even if OpenRouter is operational, there is no interface to call it because Open WebUI itself is off. If continuity without the Mac is a requirement, this is the wrong scenario: choose the runbook with a VPS.

### When the internet or Cloudflare is unavailable

The process and Qwen stay on the Mac, and the maintenance port remains at:

```text
http://127.0.0.1:3000
```

However, after go-live the cookies will be marked `Secure` and the browser will not send them over HTTP. Therefore, **authenticated offline use is not automatic**. There are two options:

1. configure trusted local HTTPS — more convenient, but out of scope for this first runbook; or
2. with Tunnel/WebUI stopped, temporarily change the two cookie flags to `false`, start in loopback only, use it locally and restore `true` before re-enabling the Tunnel.

Open WebUI's native authentication makes that recovery possible; the origin does not depend on Cloudflare identity headers.

---

## 2. Domain and services

| Item | Value |
|---|---|
| Public WebUI | `https://chat.seudominio.com` |
| Local WebUI | `http://127.0.0.1:3000` |
| Local Qwen | `http://127.0.0.1:8084/v1` |
| Model ID | `qwen38-omlx` |
| Tunnel | `openwebui-mac` |
| Reserved apex | `seudominio.com` and `www.seudominio.com` |

Public state verified on 25/08/2026:

- `seudominio.com` is delegated to `jacob.ns.cloudflare.com` and `connie.ns.cloudflare.com`;
- `chat.seudominio.com` is a CNAME proxied to the Tunnel `openwebui-mac`, with no residential `A`/`AAAA`;
- the Tunnel is `healthy`, with HA connections ready;
- `llm-home.seudominio.com` does not exist;
- no MX is published for `seudominio.com`.

The hostname **`chat.seudominio.com`** does not use Cloudflare Access in this deployment. The OTP application created later protects exclusively `browser.seudominio.com` and does not cover or inherit to the chat. There are five known internal accounts: one admin and four regular accounts. Public signup is disabled; new accounts should only be provisioned deliberately by an administrator. The login screen is public and protected by a strong password, edge rate limiting and Open WebUI's internal limiter.

### Fundamental rule

Only Open WebUI will be published. Do not create:

- `llm-home.seudominio.com` in this scenario;
- `A`/`AAAA` record for the residential IP;
- port forwarding on the router;
- `0.0.0.0` bind for Open WebUI or Qwen;
- direct browser connection to `8084`.

---

## 3. Prerequisites

On the Mac:

- macOS on Apple Silicon;
- Python 3.11 or 3.12 — Open WebUI does not support 3.13 in this version;
- `seudominio.com` domain active on Cloudflare;
- Cloudflare Zero Trust account;
- `qwen-omlx` already installed and verifiable;
- space for database, uploads and backups;
- password manager for credentials;
- `cloudflared` only when you reach the Tunnel phase.

This guide chooses a native Python install because:

- the WebUI and Qwen share the same host;
- `127.0.0.1:8084` works directly;
- there is no `host.docker.internal` translation;
- Docker does not have to be installed just for the interface.

Do not reuse oMLX's private Python environment. Open WebUI will have its own venv.

---

## 4. Isolated layout on the Mac

```text
~/services/open-webui-mac/
├── app/                # Python venv
├── data/               # database, uploads and persisted configuration
├── secrets/            # owner-only files
├── backups/            # encrypted backups only
├── env                 # configuration without secret values
└── logs/               # LaunchAgent stdout/stderr
```

Create:

```bash
umask 077
mkdir -p ~/services/open-webui-mac/{app,data,secrets,backups,logs}
chmod 700 ~/services/open-webui-mac \
  ~/services/open-webui-mac/{app,data,secrets,backups,logs}
```

Do not use `~/.open-webui` implicitly; the explicit path simplifies backup and rollback.

---

## 5. Install Open WebUI in a private venv

> This section records the commands run in the deployment. On a reinstall, use a new directory/venv and restore the database only after validating compatibility; do not overwrite the working environment.

### 5.1 Create the environment

The real deployment used Homebrew Python 3.12:

```bash
brew install python@3.12
cd ~/services/open-webui-mac
/opt/homebrew/bin/python3.12 -m venv app/venv
source app/venv/bin/activate
python -m pip install --upgrade pip
python -m pip install 'open-webui==0.11.0'
python -c "from importlib.metadata import version; print(version('open-webui'))"
python -m pip check
```

The `open-webui --version` CLI does not exist in `v0.11.0`; use Python metadata. Do not let `python3` pick the global 3.14/3.13 version, incompatible with this release.

### 5.2 Pin dependencies

After validating the install:

```bash
python -m pip freeze > app/requirements-working.txt
shasum -a 256 app/requirements-working.txt \
  > app/requirements-working.txt.sha256
```

`pip freeze` records the working environment, but it is not a full lock with hashes for every wheel. For a stronger supply-chain reinstall, download the wheels, record hashes and use `--require-hashes` in a later step.

### 5.3 Generate the WebUI secret

```bash
umask 077
openssl rand -hex 32 > secrets/webui-secret-key
chmod 600 secrets/webui-secret-key
```

This key signs sessions and protects specific supported data. It should not be read as generic encryption of the API keys persisted in the connections; treat `data/` and backups as secrets.

---

## 6. Hardened configuration

Create `~/services/open-webui-mac/env` with mode `0600`. The file contains configuration, but the WebUI secret will stay separate:

```dotenv
ENV=prod
UVICORN_WORKERS=1
DATA_DIR='/Users/SEU_USUARIO/services/open-webui-mac/data'
WEBUI_URL='https://chat.seudominio.com'
CORS_ALLOW_ORIGIN='https://chat.seudominio.com'
DEFAULT_USER_ROLE='pending'
ENABLE_SIGNUP='false'
ENABLE_INITIAL_ADMIN_SIGNUP='false'

ENABLE_PASSWORD_VALIDATION='true'
PASSWORD_VALIDATION_REGEX_PATTERN='^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{12,}$'
PASSWORD_VALIDATION_HINT='Minimum of 12 characters with uppercase, lowercase, number and symbol.'
JWT_EXPIRES_IN='4h'

# Active final state. Headless bootstrap does not require an HTTP browser session.
WEBUI_SESSION_COOKIE_SECURE='true'
WEBUI_SESSION_COOKIE_SAME_SITE='strict'
WEBUI_AUTH_COOKIE_SECURE='true'
WEBUI_AUTH_COOKIE_SAME_SITE='strict'

HSTS='max-age=31536000;includeSubDomains'
XFRAME_OPTIONS='DENY'
XCONTENT_TYPE='nosniff'
REFERRER_POLICY='strict-origin-when-cross-origin'
PERMISSIONS_POLICY='camera=(),microphone=(),geolocation=()'

ENABLE_OLLAMA_API=false
ENABLE_OPENAI_API=true
ENABLE_OPENAI_API_PASSTHROUGH=false
ENABLE_DIRECT_CONNECTIONS=false
ENABLE_COMMUNITY_SHARING=false
# true only for the audited local Browser HITL Tool; regular users
# stay without workspace.tools/import/export in the persisted permissions.
ENABLE_PLUGINS=true
# required so that server-side Tools/Functions keys do not stay in clear JSON
ENABLE_VALVE_ENCRYPTION=true
ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS=false
# The checkpoint/oMLX announces 262,144 tokens. The estimated trigger at 245,760
# provides a nominal margin of 16,384; the facade enforces prompt+output at the real ceiling.
ENABLE_CONTEXT_COMPACTION=true
CONTEXT_COMPACTION_MODEL='local.qwen38-omlx'
CONTEXT_COMPACTION_TOKEN_THRESHOLD=245760
CONTEXT_COMPACTION_TOKEN_CAP=245760
CONTEXT_COMPACTION_RETENTION_PERCENTAGE=40
ENABLE_CODE_EXECUTION=false
ENABLE_CODE_INTERPRETER=false
ENABLE_WEB_SEARCH=false
ENABLE_LOCAL_WEB_FETCH=false
ENABLE_AUTOMATIONS=false
ENABLE_SUBAGENTS=false
ENABLE_IMAGE_GENERATION=false
ENABLE_RAG_LOCAL_WEB_FETCH=false
ENABLE_PROFILE_IMAGE_URL_FORWARDING=false
ENABLE_API_KEYS=false
ENABLE_CHANNELS=false
ENABLE_CALENDAR=false
SAFE_MODE=true
ENABLE_VERSION_UPDATE_CHECK=false
RAG_EMBEDDING_MODEL_TRUST_REMOTE_CODE=false
RAG_EMBEDDING_MODEL_AUTO_UPDATE=false
RAG_EMBEDDING_MODEL=''
BYPASS_EMBEDDING_AND_RETRIEVAL=true
USER_AGENT='OpenWebUI-local/0.11.0 (chat.seudominio.com)'

RAG_FILE_MAX_SIZE=25
RAG_FILE_MAX_COUNT=5
RAG_ALLOWED_FILE_EXTENSIONS='pdf,txt,md,docx,csv'

AUDIT_LOG_LEVEL=METADATA
ENABLE_AUDIT_LOGS_FILE=true
AUDIT_LOG_FILE_ROTATION_SIZE=10MB
LOG_FORMAT=json
GLOBAL_LOG_LEVEL=INFO
AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST=5
```

Replace `SEU_USUARIO` with the output of `id -un`; do not leave the placeholder in the real file. The single quotes are deliberate: the file will be read by `zsh`, and regex, `;` and parentheses cannot stay as loose shell syntax.

```bash
chmod 600 ~/services/open-webui-mac/env
zsh -n ~/services/open-webui-mac/env
```

### ConfigVar

Several settings are persisted in the database after the first start. A later change only in the `env` file may not beat the saved value. After each change, check the effective state in the Admin Panel. Do not disable persistent config without understanding that UI changes will stop persisting.

In this environment, automatic compaction was also persisted in **Admin Panel → Settings → Interface**, with model `local.qwen38-omlx`, threshold/cap of `245760` and retention of `40%`. The `local.qwen38-omlx` workspace model keeps `compact_token_threshold=245760`. The checkpoint and the tokenizer declare a native maximum of `262144`, and oMLX announces the same value as the total context window. The threshold provides `16384` tokens of **nominal margin**, not a guaranteed partition: the estimate happens before some injections and can reduce the available output. The safe facade counts the final rendered prompt and authoritatively enforces `prompt + output <= 262144`. Compaction writes a summary checkpoint and preserves the visible chat messages.

---

## 7. Local administrator bootstrap

### 7.1 Load configuration without leaking the secret into `argv`

Create an owner-only launcher:

```bash
cat > ~/services/open-webui-mac/app/start-open-webui.sh <<'SH'
#!/bin/zsh
set -euo pipefail
umask 077
ROOT="$HOME/services/open-webui-mac"
set -a
source "$ROOT/env"
set +a
export WEBUI_SECRET_KEY="$(<"$ROOT/secrets/webui-secret-key")"
exec "$ROOT/app/venv/bin/open-webui" serve \
  --host 127.0.0.1 \
  --port 3000
SH
chmod 700 ~/services/open-webui-mac/app/start-open-webui.sh
```

The secret appears in the process environment, not on the command line. The same user and root can still read it; that is inherent to the process. Do not enable shell tracing and do not log the environment.

### 7.2 Headless bootstrap used in the deployment

A random 48-character password was generated in a `0600` file, without being displayed in the chat:

```bash
openssl rand -base64 36 | tr -d '\n' > ~/services/open-webui-mac/secrets/admin-password
chmod 600 ~/services/open-webui-mac/secrets/admin-password
```

A temporary launcher loaded only on the first start:

```bash
ROOT="$HOME/services/open-webui-mac"
export WEBUI_ADMIN_EMAIL='<EMAIL_ADMIN>'
export WEBUI_ADMIN_NAME='<NAME_ADMIN>'
export WEBUI_ADMIN_PASSWORD="$(<"$ROOT/secrets/admin-password")"
```

After confirming exactly one `admin` user in the database at bootstrap, the service was restarted with `start-open-webui.sh`, without `WEBUI_ADMIN_PASSWORD` in the permanent environment. `ENABLE_SIGNUP=false` remained effective. The generated password passed the complexity regex (`PASS`, without displaying its value), was used in the browser and the clipboard was cleared.

After saving the credential in the password manager and validating the HTTPS login, `secrets/admin-password` should be removed. The current backup script already excludes that file; old backups generated before this hardening may still contain the bootstrap copy and require an explicit retention/removal decision and possible password rotation.

### 7.3 HTTPS gate before publication

Edit the `env` file:

```dotenv
WEBUI_SESSION_COOKIE_SECURE=true
WEBUI_AUTH_COOKIE_SECURE=true
```

From that moment on, use `https://chat.seudominio.com` in the browser. Secure cookies will not be sent to `http://127.0.0.1:3000`; for local maintenance, use an appropriate SSH/HTTPS tunnel or revert temporarily with the service stopped and no public exposure.

---

## 8. Connect Qwen over loopback

### 8.1 Verify and start the model

```bash
qwen-omlx verify --quick
qwen-omlx start
qwen-omlx status
lsof -nP -iTCP:8084 -sTCP:LISTEN
```

The listener must be exactly:

```text
127.0.0.1:8084
```

### 8.2 Test without exposing the key in `argv`

```bash
umask 077
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT INT TERM
QWEN_KEY_FILE="$HOME/models/qwen38-omlx/state/api-key"

{
  printf 'silent\nshow-error\nfail-with-body\n'
  printf 'url = "http://127.0.0.1:8084/v1/models"\n'
  printf 'header = "Authorization: Bearer %s"\n' "$(<"$QWEN_KEY_FILE")"
} > "$TEST_DIR/qwen.curlrc"
chmod 600 "$TEST_DIR/qwen.curlrc"
curl --config "$TEST_DIR/qwen.curlrc"
```

It must list `qwen38-omlx` with `max_model_len=262144`. The checkpoint and the tokenizer stay native at `262144`; `state/settings.json` and `state/model_settings.json` must agree with each other on the allowed effective profile (`262144` active or `32768` rollback), and `qwen-omlx verify --quick` fails if that set becomes inconsistent. The safe facade turns `8192` into a real ceiling — not just a default —, writes the reduced value into the request object before starting any deferred response and guarantees `prompt + output <= 262144` in completion and chat completion. Speculative MTP also reduces depth near the limit and checks the real offsets of the target caches and of the MTP head, preventing an internal forward from advancing beyond the window even when the speculative tokens would not be emitted.

The persistent prefix cache uses up to `40GB` in `~/models/qwen38-omlx/state/cache`. This does not pre-allocate 40 GB of RAM nor make the 256K prefill instant; it is just the SSD ceiling for prefix reuse. The larger total window increases memory and latency as the context actually filled grows.

### 8.3 Register in Open WebUI

```text
Admin Settings → Connections → OpenAI → Add Connection
```

Fields:

```text
URL:       http://127.0.0.1:8084/v1
API Key:   contents of ~/models/qwen38-omlx/state/api-key
Prefix ID: local
Model IDs (Filter): qwen38-omlx
```

No custom headers, Service Token or Cloudflare are needed between WebUI and Qwen. This connection is server-to-server on the same Mac's loopback.

The connection is global, but `v0.11.0` requires a model entry with access control for regular users. In **Admin Settings → AI → Models**, mark `local.qwen38-omlx` as **Public** (`read` for `user:*`). Do not configure the connection/API key in each account and do not enable Direct Connections. **Selected** or **Pinned** only changes the initial experience; it does not replace the Public permission.

### 8.4 Test chat

1. select the local model in the WebUI;
2. send a short prompt;
3. confirm streaming;
4. check `qwen-omlx status`;
5. confirm that the logs do not show the API key or the prompt at an undue level;
6. test a long response.

### 8.5 Validate the context window

The gates and numbers in this subsection were run on the deployed uncensored profile `qwen38-omlx`. They are historical evidence of that process, not empirical validation of the `fcmeyer` checkpoint; the new guide requires its own canary.

The validation of `262144` must separate five gates:

1. **native metadata:** `config.json:text_config.max_position_embeddings` and `tokenizer_config.json:model_max_length` equal to `262144`;
2. **effective runtime:** `/v1/models` announces `max_model_len=262144` and `/v1/models/status` shows `model_context_length=max_context_window=262144`;
3. **acceptance above the old limit:** a real inference with more than `32768` prompt tokens produces output and returns usage metrics;
4. **deep canary:** a prompt close to the operational threshold confirms prefill, memory and streaming without exceeding the total window;
5. **boundary after promotion:** the four real HTTP modes reach exactly the total `262144` without speculative overshoot, scope leakage or memory abort.

Gate 3 was run after the restart with `40012` prompt tokens, 4 output tokens, streaming, `finish_reason=length` and an identical count between tokenizer and server. The prefill measured `175.83 prompt tok/s` and the TTFT was `227.56 s`; this proves capacity above 32K and also evidences the cost of real context.

Gate 4 also passed: `245760` prompt tokens, 1 output token, streaming, `finish_reason=length`, `96.08 prompt tok/s`, TTFT of `2557.78 s` and wall time of `2558.19 s` (~42m38s), with no memory guard abort and a healthy service at the end. That canary reused `38912` tokens and reprocessed `206848`; therefore, it proves capacity close to the threshold in that measured state, not a fully cold prefill nor long-context quality.

After independent review and promotion of the request-scope and Lightning MTP boundary guards, a fifth gate covered the four real HTTP modes in the new process:

| Endpoint/mode | Effective prompt + output | Wall time | Cached prefix |
|---|---:|---:|---:|
| Chat streaming | `262140 + 4` | `71.301 s` | `258048` |
| Chat non-streaming | `262143 + 1` | `36.497 s` | `260096` |
| Raw completion streaming | `262140 + 4` | `36.467 s` | `260096` |
| Raw completion non-streaming | `262143 + 1` | `36.126 s` | `260096` |

All finished exactly at `262144` tokens, with `finish_reason=length`; each call asked for `8192` tokens, and the facade bound to the request only the `4` or `1` remaining token. This gate proves live boundary safety — not cold prefill. There was no `_MtpSafetyViolation` and no memory guard abort. The largest momentary RSS observed during the campaign was ~`30.52 GiB`, the lowest system free memory was `33%`, and there was no continuous peak trace.

The startup verifier complements the canaries with an ASGI matrix across the four completion/chat × streaming/non-streaming modes, concurrency/error, isolated `32768` rollback profile, MTP edge limits and byte-for-byte comparison of the critical installed sources against the pinned wheel. After the canaries, both the quick and the full cryptographic verifier passed; an authenticated smoke test through the Open WebUI proxy also returned HTTP 200 from the `local.qwen38-omlx` model. The structured evidence, including hashes of the promoted code, is in `~/models/qwen38-omlx/context-256k-validation.json`.

Do not use only the value displayed by the frontend as evidence. Deep context has a real cost: with concurrency `1`, a long request occupies the model during prefill. For the 16 full-attention layers, resident KV grows approximately `64 KiB` per token in BF16 — about `4 GiB` at `65536` tokens and `16 GiB` at `262144` — on top of the weights, the recurrent state and the transients. MTP priming can add approximately `4 KiB` per token, close to `1 GiB` at the ceiling. The startup log that estimates `16 MiB` per 64-token block uses all 64 layers as a conservative block estimate and should not be multiplied as the hybrid's resident KV. The `16384` difference in the threshold is nominal margin: `8192` can be used by the output and the rest absorbs, without guarantee, system prompt, Tools and estimation error. Schemas added after the compaction decision can consume that margin, reduce the effective output or cause rejection by the total guard; they do not automatically bring compaction forward.

---

## 9. Dedicated Open Terminal per user

The integrated terminal was deployed with one **Open Terminal `0.12.1` container per approved account**. Everyone keeps using only `https://chat.seudominio.com`; when selecting the terminal icon, Open WebUI opens a session in that user's already existing container.

```text
chat.seudominio.com
  ├── user A → authenticated proxy → container A → ~/AI-Workspace/a
  ├── user B → authenticated proxy → container B → ~/AI-Workspace/b
  └── user C → authenticated proxy → container C → ~/AI-Workspace/c
```

A container is not created on every click. The container is provisioned once; each use creates or resumes a session inside it. The containers use:

- official image pinned by digest;
- random port in the `3101–3199` range, published only on `127.0.0.1`;
- dedicated Docker network with a single container;
- 3 CPUs, 8 GiB of RAM and a 256-process limit;
- `no-new-privileges` and all capabilities dropped;
- no Docker socket, `$HOME`, `~/.ssh`, Keychain or another user's directory;
- an individual API key in a `0600` file, absent from `argv`, metadata and logs;
- a single bind mount of `~/AI-Workspace/<slug>` to `/workspace`.

Proxy responses receive CSP with `sandbox allow-scripts`, without `allow-same-origin`, to reduce access from HTML generated by the terminal to the Open WebUI origin.

### 9.1 Onboarding a new user

Creating an Open WebUI account does not automatically provision a container. The process deliberately requires an administrative action:

1. create or approve the account at `chat.seudominio.com`;
2. keep `role=user`, except when full administration is really needed;
3. run:

```bash
~/services/open-webui-terminals/provision-user.sh
```

The command lists accounts with masked e-mails and asks for the user and the slug. For explicit automation:

```bash
~/services/open-webui-terminals/provision-user.sh \
  --user '<EXACT_EMAIL_OR_UUID>' \
  --slug '<short-identifier>'
```

It is idempotent and runs these gates before finishing:

- container health;
- `/execute` without a key returns `401`;
- authenticated `pwd` exits with code zero in `/workspace`;
- the connection is registered through the supported administrative API;
- the assigned user sees the terminal;
- other regular users do not see it;
- the key does not appear in Docker metadata, logs or process snapshot.

Afterwards, the user must log out and in again or do a hard refresh. The personal terminal will appear in the selector under **System**.

Operational inventory:

```bash
~/services/open-webui-terminals/provision-user.sh --list
docker ps --filter 'name=openwebui-terminal-'
```

Owner-only state lives in `~/services/open-webui-terminals/state.json`; keys live under `secrets/<slug>/api-key`. Both are already part of the encrypted control-plane backup. The `~/AI-Workspace/<slug>` folders are not part of that archive and require their own backup. **There is still no deprovisioning command:** do not remove a container, connection or workspace manually without a procedure that preserves the user's files.

### 9.2 Limit of the administrative ACL

Regular users see only the terminal granted to their own UUID. An `admin` user is root-equivalent in Open WebUI and can see/reconfigure every integration by design; ACL is not a boundary against the instance operator. Use `role=user` for anyone who does not need to administer the service.

### 9.3 Visual browser and authentication

Open Terminal provides shell, files, Git and tools. For a visual Chromium, manual login, MFA or CAPTCHA, do not share authenticated profiles nor mount the macOS Chrome profile.

After the initial Computer deployment, a separate **multi-user universal HITL POC** was added, documented in [`04-browser-hitl-multi-user-poc.md`](04-browser-hitl-multi-user-poc.md). It keeps isolated persistent profiles for admin and user-a, ties ownership to the Open WebUI UUID and enforces a server-side lock between agent and human. The broker is already published at `browser.seudominio.com` behind Cloudflare Access with One-Time PIN exclusively on that hostname; the low-risk mobile E2E is still pending, and high-value accounts remain outside the approved scope. `chat.seudominio.com` stays without Access/OTP, protected only by the Open WebUI login.

The Computer is not needed for those who use only chat and terminal.

The deployed hybrid profile keeps Computer active only for admin. user-a and user-b have optional containers stopped, without auto-restart; user-c and user-d have no Computer. The active environment uses:

- local interface `http://renato.localhost:3011`, published only on `127.0.0.1:3011`;
- private model `cptr/admin` on `chat.seudominio.com`, with a read grant only to admin's UUID;
- workspace `/workspaces/renato` over the same Mac folder used by Open Terminal;
- managed, persistent Chromium in `/data/chromium-renato`, never the macOS Chrome profile;
- Xvfb without a TCP listener, active Chromium sandbox, seccomp default-deny, zero capabilities and `no-new-privileges`;
- password manager, autofill, Browser Sign-in and Sync disabled by policy;
- Qwen registered in the Computer with an encrypted key and a gateway key stored only as a hash inside the Computer;
- operational log at `WARNING` so as not to record the encoder's ephemeral tokens, and a separate audit log at `METADATA`.

The local image derives from the official Computer digest `0.9.21` and includes a versioned/fail-closed patch of two calls so that managed visual tabs use the same persistent CDP as the browser tools. That lets manual takeover and automation share cookies without using the personal Chrome mode.

The Computer **is not published remotely**. `browser.seudominio.com` publishes only the hardened Browser HITL broker, not port `3011` nor the Computer interface. For future access to the Computer outside the Mac, configure Tailscale or another separate Access hostname; never publish port `3011` with only the local password.

---

## 10. Optional OpenRouter

It is possible to add OpenRouter even without a VPS:

```text
URL:       https://openrouter.ai/api/v1
API Key:   dedicated key with a spend limit
Prefix ID: openrouter
```

Use **Model IDs (Filter)** for a small allowlist. Review retention, logging and training for each selected provider.

Unavoidable limitation: with the Mac off, Open WebUI is also off and OpenRouter is not reachable through this interface.

---

## 11. Chosen public authentication

The deployment started with Cloudflare Access + One-time PIN and the Open WebUI internal login. After the first test, the owner chose to remove the OTP and keep only the native login.

Final state:

- there is no Access application for `chat.seudominio.com`;
- there is no `originRequest.access` validation in the Tunnel;
- the Open WebUI login screen is publicly reachable;
- signup is disabled both in the effective and in the persisted configuration;
- there are five known internal accounts: one admin and four regular accounts;
- the `local.qwen38-omlx` model is public to authenticated users and was validated with SSE inference using a regular account;
- the `cptr/admin` agentic model is visible and invocable only by admin among the current accounts;
- the admin's random 48-character password had its complexity policy validated without exposing the value;
- the cookie is `Secure`, `HttpOnly` and `SameSite=Strict`;
- an incorrect login does not leak internal details;
- the Cloudflare rate limit blocks after five `POST /api/v1/auths/signin` per IP in 10 seconds, for 10 seconds.

This choice reduces defense in depth in exchange for UX. To restore MFA/OTP in the future, recreate an exact-e-mail Access application before re-enabling `originRequest.access` with the corresponding AUD.

---

## 12. Create the Tunnel on the Mac

### 12.1 DNS state

Confirm in the dashboard:

```text
Websites → seudominio.com → Overview → Status: Active
SSL/TLS → Universal SSL: Active
```

Do not create `A`/`AAAA` for the residential IP. The Published application route manages the proxied DNS for `chat.seudominio.com`. Resolve any conflicting record first.

### 12.2 Create the remote Tunnel

```text
Networking → Tunnels → Create tunnel
Name: openwebui-mac
Type: cloudflared
System: macOS arm64
```

Do not run a command with a literal token. Write the token directly into an owner-only file and clear the clipboard:

```text
~/.config/cloudflared-openwebui/tunnel.token   mode 0600
```

Use `cloudflared >= 2025.4.0` with `--token-file`.

### 12.3 Tunnel LaunchAgent

Deployed file:

```text
~/Library/LaunchAgents/com.local.cloudflared-openwebui.plist
```

Deployed `ProgramArguments`:

```xml
<array>
  <string>/opt/homebrew/bin/cloudflared</string>
  <string>tunnel</string>
  <string>--config</string>
  <string>/Users/SEU_USUARIO/.config/cloudflared-openwebui/config.yml</string>
  <string>--no-autoupdate</string>
  <string>--metrics</string>
  <string>127.0.0.1:20241</string>
  <string>--loglevel</string>
  <string>info</string>
  <string>run</string>
  <string>--token-file</string>
  <string>/Users/SEU_USUARIO/.config/cloudflared-openwebui/tunnel.token</string>
</array>
```

Use the path from `command -v cloudflared`; do not assume Homebrew or architecture. The LaunchAgent starts only after login. Do not enable automatic login just for this.

Keep the log at `info`; debug can record headers and sensitive information.

### 12.4 Published application route

In the `openwebui-mac` Tunnel:

```text
Route type:  Published application
Hostname:    chat.seudominio.com
Service URL: http://127.0.0.1:3000
```

The remote configuration contains only that rule and a catch-all `http_status:404`. By owner decision, **Protect with Access is disabled**; authentication happens in Open WebUI. Do not create a route for `127.0.0.1:8084`.

---

## 13. Auto-start of Open WebUI, Tunnel and Qwen

The active deployment uses three user LaunchAgents:

| Label | Process | Policy |
|---|---|---|
| `com.local.openwebui` | Open WebUI | `RunAtLoad` + `KeepAlive` |
| `com.local.cloudflared-openwebui` | Cloudflare Tunnel | `RunAtLoad` + `KeepAlive` |
| `com.local.qwen-omlx` | Qwen/oMLX | `RunAtLoad`; the process stays in the foreground under `launchd` |

They start when the owner logs into macOS; they do not turn the Mac into a service available before login. All three plists passed `plutil -lint`, and a controlled restart of the `launchd` session proved joint recovery followed by a public completion. No physical reboot of the Mac was done.

WebUI file:

```text
~/Library/LaunchAgents/com.local.openwebui.plist
```

Essential structure:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local.openwebui</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/SEU_USUARIO/services/open-webui-mac/app/start-open-webui.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/SEU_USUARIO/services/open-webui-mac</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/SEU_USUARIO/services/open-webui-mac/logs/stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/SEU_USUARIO/services/open-webui-mac/logs/stderr.log</string>
</dict>
</plist>
```

Replace all placeholders. Validate before loading:

```bash
plutil -lint ~/Library/LaunchAgents/com.local.openwebui.plist
```

Use `launchctl bootstrap gui/$(id -u) ...`/`bootout` according to the macOS version. Do not use `sudo`: MLX/Metal and the private files belong to the user.

Qwen was deliberately included in auto-start. The `start-qwen-omlx.sh` launcher keeps compatibility with the existing controller's PID file, refuses to replace a foreign PID and never changes the `127.0.0.1:8084` bind.

### 13.1 Startup order

The three LaunchAgents are independent; there is no guarantee that Qwen is already ready when the WebUI opens. That is acceptable: the WebUI and the Tunnel come up without the model, and the local connection becomes available as soon as Qwen finishes loading. Validation must wait for the health checks before testing chat. Do not create an infinite restart loop nor pass secrets in arguments.

---

## 14. Acceptance tests

### 14.1 Local

```bash
curl --fail http://127.0.0.1:3000/health
lsof -nP -iTCP:3000 -sTCP:LISTEN
lsof -nP -iTCP:8084 -sTCP:LISTEN
```

Expected:

```text
Open WebUI → 127.0.0.1:3000
qwen-omlx → 127.0.0.1:8084
```

Fail if `*:3000`, `0.0.0.0:3000`, `*:8084` or `0.0.0.0:8084` appears.

Final result of 25/08/2026:

- WebUI on `127.0.0.1:3000`;
- Qwen on `127.0.0.1:8084`;
- Tunnel metrics on `127.0.0.1:20241`;
- `qwen-omlx verify --quick` and `pip check` passed;
- no deployed key, password, token or secret was found in the logs.

### 14.2 Phone

On 4G/5G, outside Wi-Fi:

1. open `https://chat.seudominio.com`;
2. confirm that the screen is directly the Open WebUI login, with no OTP;
3. log in with `<EMAIL_ADMIN>` and the password from the password manager;
4. chat with Qwen;
5. confirm streaming;
6. open an anonymous tab and check that the login reappears;
7. confirm that signup is not offered.

The final public automated gate authenticated the admin over HTTPS, received a `Secure`, `HttpOnly` and `SameSite=Strict` cookie, discovered `local.qwen38-omlx`, received more than one SSE event with the expected content and the `[DONE]` terminator. Without authentication, the users API answered `401`. A second run using the regular account confirmed visibility and inference of the public model.

The public routes `/signup`, `/docs`, `/openapi.json` and `/redoc` return the SPA HTML shell in `v0.11.0`; they expose neither a signup form nor an OpenAPI specification. An extra block at the edge would be just an optional reduction of scanner noise, not a fix for an exposed documentary API.

### 14.3 Negative

- stop `qwen-omlx`: the WebUI opens, the local model fails in a controlled way;
- stop Open WebUI: `chat.seudominio.com` returns origin unavailable;
- stop the Tunnel: the WebUI stays local, the public hostname fails;
- turn off the internet: WebUI/Qwen processes stay local, but HTTP login requires the controlled cookie-flag procedure or local HTTPS; public access and OpenRouter fail;
- turn off the Mac: everything in this scenario goes offline.

---

## 15. Mandatory hardening

### Open WebUI

- bind only on `127.0.0.1:3000`;
- native authentication enabled;
- signup closed after the admin;
- short JWT; without Redis, logout does not immediately revoke an issued token;
- Secure cookies for the HTTPS hostname;
- CORS only `https://chat.seudominio.com`;
- plugin runtime enabled only for the reviewed Browser HITL Python Tool; creation/import/export by regular users and automatic pip install stay disabled; generic code execution stays disabled;
- passthrough and direct connections disabled;
- web search, automations and subagents disabled until review;
- uploads limited; dot-less allowlist (`pdf,txt,md,docx,csv`) validated with `.txt → 200` and `.exe → 400`;
- audit log `METADATA`, never bodies by default;
- pinned venv and version;
- owner-only files/directories.

### Cloudflare

| Control | State |
|---|---|
| CNAME proxied to the Tunnel, no residential IP | validated via API |
| `chat.seudominio.com`: public Open WebUI login, no Access/OTP | validated via API and HTTPS |
| Login rate limit: 5 requests/IP/10 s, 10 s block | validated with `429` |
| Tunnel Token in a file, not in `argv` | validated |
| Metrics only on `127.0.0.1:20241` | validated |
| Remote catch-all `http_status:404` | validated via API |
| Managed Free Ruleset/DDoS L7 | expected default coverage; specific configuration not inventoried |
| Alert when the Tunnel is offline | pending confirmation |
| Absence of port forwarding on the router | pending router verification |

The normative rule remains: do not open any inbound port on the router.

### Qwen

- `127.0.0.1:8084` and Bearer required;
- current minimal facade;
- egress sandbox kept;
- no MCP, web, remote code, tools or model mutation;
- concurrency 1;
- native/effective/announced window at `262144` tokens and maximum output at `8192`;
- `safe` memory guard stays enabled; do not raise `iogpu.wired_limit_mb` just to chase context without measuring real pressure;
- SSD cache limited to `40GB` and no reserved hot cache;
- `qwen-stable` preserved;
- do not publish the API on the Tunnel.

### Deployed uncensored model

This warning refers specifically to the current `qwen38-omlx`/`pyros-vault` profile, not to the `fcmeyer` checkpoint recommended for new installs. The deployed model is refusal-removed. Do not offer anonymous access nor connect it automatically to shell, files, network, e-mail, SSH or cloud. Outputs are untrustworthy and should not be executed without human validation.

---

## 16. Local backup and restore

`data/` holds database, chats, uploads, configurations and recoverable connection credentials. Every backup must be encrypted.

In the deployment, `app/backup-open-webui.sh` creates an online snapshot consistent with `sqlite3 .backup`, packages data, required secrets, launchers, plists and recovery metadata and encrypts the result with `age`. It uses `set -euo pipefail`, writes first to `.partial`, validates tar and SQLite before the final `mv` and deliberately excludes `secrets/admin-password`.

The most recent general backup, `open-webui-mac-20260827-060049.tar.gz.age`, had checksum, isolated decryption, tar read and `PRAGMA integrity_check` validated. Besides the five users, provisioner/state, four terminal keys, artifacts/patches and the Computer gateway key, it includes the Qwen control plane, owner-only configurations/secrets, the pinned oMLX wheel, minimal checkpoint metadata, `context-256k-validation.json` and the durable raw matrix `context-256k-boundary-live-results.json`. It deliberately excludes the 17 GB shards, the rebuildable venv, logs and the 40 GB SSD cache; restoring the model requires rebuilding from the pinned identities and `qwen-omlx verify`. No `AI-Workspace` folder, Chromium volume or bootstrap password enters the general backup. The separate Computer volume, including database, password hash, chats and Chromium profile, is in the encrypted backup `computer-renato-data-20260826-114648.tar.gz.age`, also validated by isolated restore and SQLite integrity. Earlier backups remain intact and the first three general backups may contain the bootstrap password.

The identity is at `~/.config/open-webui-backup/identity.txt` (`0600`). **There is still no independent disaster copy:** copy the `.age` file to an external destination and keep the private identity at a destination separate from the encrypted backup. Do not put both on the same media or account; alternatively, protect the identity with additional encryption/passphrase and keep the passphrase separately. On 25/08/2026, only `disk0` was available: the Time Machine volume `/Volumes/TimeMachine` belongs to the same internal physical disk and does not protect against failure of that SSD.

The authoritative operational source is:

```bash
~/services/open-webui-mac/app/backup-open-webui.sh
```

Do not replace the script with an ad hoc pipeline without `pipefail`, partial file, decryption validation and `PRAGMA integrity_check`. To validate the disaster copy, use the separately stored identity to decrypt an **external copy** into a temporary directory and confirm tar + SQLite without overwriting the active state.

Target policy not yet automated:

- daily and before upgrades;
- 7 daily, 4 weekly and 6 monthly;
- intended RPO of 24 h, not yet achieved by monitored scheduling;
- quarterly restore into a separate directory/user;
- never overwrite the failed state before diagnosing.

Restore:

1. stop Open WebUI;
2. verify the checksum;
3. extract into a new directory, not over the original;
4. restore compatible venv/version, `data`, `secrets` and `env`;
5. start manually on another loopback port;
6. validate login, history, Qwen and OpenRouter;
7. only then promote the restore.

Database migrations can prevent a package-only downgrade; restore package and data from the same point.

---

## 17. Upgrade and rollback

Before upgrading:

1. review the release notes;
2. generate and validate an encrypted backup;
3. clone the current venv or create a new venv alongside;
4. install the new version in the new environment;
5. start it on a temporary loopback port;
6. validate migrations and essential functions;
7. swap the LaunchAgent only after approval;
8. preserve the previous venv and backup during retention.

A real rollback may require restoring the previous database, not just re-enabling the old venv.

### Rollback specific to the 256K window

If deep prompts cause memory pressure or unacceptable operational latency, revert consistently — do not change only the number shown in the WebUI:

1. in `~/models/qwen38-omlx/state/settings.json`, restore `sampling.max_context_window` and `sampling.max_context_window_policy` to `32768`;
2. in `state/model_settings.json`, restore `models.qwen38-omlx.max_context_window` to `32768`; the verifier accepts only the coherent rollback pair `32768` or the native `262144`, while checkpoint/tokenizer stay pinned at `262144`;
3. in `~/services/open-webui-mac/env`, restore threshold/cap to `24000`;
4. through the Open WebUI persisted configuration, restore the global threshold/cap and the workspace model's `compact_token_threshold` to `24000`;
5. run `qwen-omlx verify --quick`; the launcher banner reads the effective cap from the JSON, with no hardcoded number;
6. restart `com.local.qwen-omlx` first, then `com.local.openwebui`;
7. require `/v1/models:max_model_len=32768`, healthy health and a short chat before ending the rollback.

The SSD cache may stay at `40GB`; reducing it back to `20GB` is optional and does not require deleting files manually. Do not use `rm -rf` on the cache during rollback; the manager applies the ceiling and compatible cleanup.

To remove remote access without deleting anything locally:

1. remove/disable the `chat.seudominio.com` route;
2. revoke the Tunnel Token;
3. stop the `cloudflared` LaunchAgent;
4. keep Open WebUI and Qwen on loopback.

---

## 18. Go-live checklist

### Local install

- [x] Python is 3.12.14, not 3.13+;
- [x] Open WebUI is in a venv separate from oMLX;
- [x] version, freeze and freeze checksum are recorded;
- [x] `DATA_DIR` is explicit and owner-only;
- [x] WebUI secret is in a `0600` file;
- [x] the first admin was created locally;
- [x] signup is closed in the effective and persisted configuration;
- [x] cookies were changed to Secure before publication;
- [x] the WebUI listener is only `127.0.0.1:3000`.

### Qwen

- [x] `qwen-omlx verify --quick` passes;
- [x] the listener is only `127.0.0.1:8084`;
- [x] the WebUI connection uses `http://127.0.0.1:8084/v1`;
- [x] the Bearer key is configured and was tested without appearing in `argv`/logs;
- [x] checkpoint, tokenizer, runtime and endpoint converge on `262144` tokens;
- [x] the facade limits output to `8192`, rejects a prompt without room, binds the ceiling to the request before streaming and guarantees `prompt + output <= 262144` in real HTTP tests;
- [x] MTP reduces drafts near the ceiling and applies a guard from the real offsets of the target/head caches, covering speculative forwards beyond the emitted tokens;
- [x] real canaries passed at `40012`, `245760` and `260000` prompt tokens, with limitations recorded in the evidence artifact;
- [x] after promotion of the final guards, chat/raw completion × streaming/non-streaming closed exactly at `262140 + 4` and `262143 + 1 = 262144`, with no MTP violation or memory abort;
- [x] Open WebUI persists threshold/cap and workspace model at `245760` after restart and the authenticated proxy kept generating from the promoted process;
- [x] coherent rollback at `32768` passed the verifier using an isolated temporary clone;
- [x] full cryptographic verification of the wheel, four shards and 12 metadata files passed;
- [x] there is no `llm-home.seudominio.com` nor a route for 8084;
- [x] streaming works publicly end to end.

### Open Terminal

- [x] four approved accounts have their own container, network, key and workspace;
- [ ] the fifth current account has not yet been provisioned in Open Terminal;
- [x] regular users see only the terminal assigned to their own UUID;
- [x] ports `3101–3104` use loopback only;
- [x] `/execute` without a key returns `401` and authenticated `pwd` returns `/workspace`;
- [x] Qwen called `run_command`; the terminal log recorded exactly `pwd`;
- [x] the proxy CSP uses sandbox without `allow-same-origin`;
- [x] Docker Desktop starts at login and containers use `restart=unless-stopped`;
- [x] state and keys enter the encrypted control-plane backup;
- [ ] `~/AI-Workspace/*` folders still need their own backup policy;
- [x] the visual Computer was initialised only for admin and stays on loopback;
- [x] `cptr/admin` is private by UUID and regular users get model unavailable when trying to invoke it;
- [x] Qwen ran exactly `pwd` in the Computer and `browser_navigate` opened `example.com`;
- [x] visual takeover, Chromium/CDP, sandbox, restart and encrypted backups were validated;
- [x] the local Browser HITL POC was validated with isolated profiles for admin/user-a, `423` lock, same-session noVNC and resumption by a new epoch;
- [x] Browser HITL POC published separately at `browser.seudominio.com`, with Access restricted to OTP, JWT/e-mail bound and chat without OTP; the low-risk mobile E2E is still missing before main accounts;
- [ ] remote access to the Computer has not been published yet; it requires Tailscale or Cloudflare Access.

### Cloudflare

- [x] `chat.seudominio.com` stays without Access/OTP per owner decision;
- [x] `browser.seudominio.com` uses separate Access/OTP and does not change the chat login;
- [x] the public chat login uses only Open WebUI native authentication;
- [x] the login endpoint rate limit was created and tested with `429`;
- [x] the Tunnel Token uses `--token-file`;
- [x] `chat.seudominio.com` points through the Tunnel, with no residential A/AAAA;
- [x] HTTPS login and public chat work;
- [x] wrong password and public signup are denied.

### Operation

- [x] the three LaunchAgents recovered the services in a controlled restart of the `launchd` session;
- [ ] automatic recovery after a physical reboot and new login has not been proven yet;
- [ ] the isolated negative Tunnel test has not been repeated yet; the local origin is independent by construction and is healthy;
- [x] the 25/08/2026 scan of the three LaunchAgents' logs found neither the deployed secret values nor the test prompt markers;
- [x] encrypted backup, decryption into a temporary directory and SQLite integrity were tested;
- [x] the hardened backup excludes `secrets/admin-password`;
- [ ] the `.age` backup and the private identity still need external copies at separate destinations;
- [ ] old backups potentially containing the bootstrap password still require a retention/removal decision and rotation;
- [ ] scheduling, 7/4/6 retention and backup failure alert are not automated yet;
- [ ] the full quarterly restore from the future external copies has not been executed yet;
- [ ] the Tunnel health alert has not been confirmed yet;
- [x] WebUI, Qwen and Tunnel metrics use loopback only, never `0.0.0.0`;
- [ ] the absence of port forwarding still needs to be confirmed on the router.

---

## 19. Recommended sequence

1. create directories and private venv;
2. install the pinned Open WebUI version;
3. create configuration and secret;
4. start on `127.0.0.1:3000`;
5. create admin and close signup;
6. validate Qwen over loopback;
7. add optional OpenRouter;
8. enable Secure cookies;
9. create the Tunnel with token-file;
10. publish only `chat.seudominio.com → 127.0.0.1:3000`;
11. create a login-specific rate limit;
12. validate HTTPS, login, denied signup and public SSE;
13. create the LaunchAgents;
14. install/start Docker Desktop;
15. provision one Open Terminal per approved user;
16. validate ACL, CSP and the Qwen tool call;
17. configure backup and monitoring.

Cloudflare Access was removed from `chat.seudominio.com` by owner choice and remains absent from the chat. Later, a separate application, restricted to One-Time PIN, was created exclusively for `browser.seudominio.com`; it does not change the Open WebUI authentication.

---

## 20. Official references

### Open WebUI

- Quick Start: <https://docs.openwebui.com/getting-started/quick-start/>
- OpenAI-compatible providers: <https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/>
- Hardening: <https://docs.openwebui.com/getting-started/advanced-topics/hardening/>
- Environment variables: <https://docs.openwebui.com/reference/env-configuration/>
- Updating: <https://docs.openwebui.com/getting-started/updating/>
- Releases: <https://github.com/open-webui/open-webui/releases>

### Cloudflare

- Create remotely managed Tunnel: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/>
- Rate limiting rules: <https://developers.cloudflare.com/waf/rate-limiting-rules/create-api/>
- Tunnel token-file/run parameters: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/>
- macOS service: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/macos/>

### OpenRouter

- Authentication: <https://openrouter.ai/docs/api/reference/authentication>

---

## 21. Conclusion

Without a VPS, the architecture is simpler: WebUI, history and inference stay on the Mac; only the interface crosses the Cloudflare Tunnel. The `qwen-omlx` API never gets a public hostname and remains protected by loopback and Bearer. In this deployment, the WebUI login screen is public by explicit decision, with a strong password, closed signup and Cloudflare rate limiting; there is no OTP/MFA at the edge.

The cost of that simplicity is availability: turning the Mac off removes the WebUI, Qwen and access to OpenRouter through this interface. That is not a misconfiguration; it is the central property of the without-VPS scenario.
