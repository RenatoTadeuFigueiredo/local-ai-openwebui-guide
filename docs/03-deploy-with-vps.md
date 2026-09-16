# Open WebUI with a VPS: always-on cloud, OpenRouter and Qwen on the Mac

> **English** · [Português](../pt-br/docs/03-deploy-with-vps.md)

**Status:** deployment runbook; no installation has been executed  
**Reference date:** 27 August 2026  
**Verified reference versions:** Open WebUI `v0.11.0`; `cloudflared` `2026.8.2`  
**Objective:** keep Open WebUI and OpenRouter available when the Mac is off, using `qwen38-official-omlx` remotely only while the Mac is online  
**Domains:** `chat.seudominio.com` for the interface and `llm-home.seudominio.com` for the protected home API

> This is exclusively the **with VPS** scenario. To run everything on the Mac, without a VPS, use [`02-deploy-macos-cloudflare-tunnel.md`](02-deploy-macos-cloudflare-tunnel.md).
>
> **Optional.** Skip this document unless you need the WebUI reachable while the Mac is powered off. The local path is the default and covers the guide's objective on its own.
>
> Because this scenario has not been executed yet, for new installs it adopts the clean-room profile [`../examples/qwen38-official-omlx/README.md`](../examples/qwen38-official-omlx/README.md): community checkpoint `fcmeyer/...@0299356…`, declared as derived from `Qwen/Qwen3.8-27B`. Install, verify and run the model's 40K canary on the Mac before publishing the API through the Tunnel.

---

## 1. Architectural guarantee

> **Cloudflare Tunnel does not host Open WebUI.** Continuity comes from the VPS, where the process and its data stay running.

```text
                       ┌────────────────────────────→ OpenRouter
Phone → Cloudflare → Open WebUI on VPS/cloud
                       └→ Cloudflare Access/Tunnel → qwen38-official on the Mac
```

If the Mac powers off:

- Open WebUI stays online;
- history, login and settings stay online;
- OpenRouter and other remote providers keep working;
- only `qwen38-official-omlx` becomes unavailable;
- when the Mac, the model and the Tunnel come back, the local model returns without migrating weights to the cloud.

If the VPS powers off, the interface becomes unavailable, even though Qwen remains usable directly on the Mac. There is no silent fallback from Qwen to OpenRouter.

---

## 2. Architecture

Two independent tunnels and two hostnames will be used:

```text
                                Internet
                                   │
                         https://chat.seudominio.com
                                   │
                    Cloudflare Access — human login
                                   │
                     Tunnel 1: openwebui-cloud
                                   │
                        Open WebUI on the VPS
                         /                 \
                        /                   \
        https://openrouter.ai/api/v1        https://llm-home.seudominio.com/v1
                                                     │
                                      Cloudflare Access — Service Auth
                                                     │
                                          Tunnel 2: qwen-home
                                                     │
                                     qwen38-official 127.0.0.1:8084
                                            on the M3 Max
```

### 2.1 Responsibility of each layer

| Component | Where it runs | Responsibility |
|---|---|---|
| Open WebUI | VPS/cloud | interface, users, history and routing to providers |
| Chat Cloudflare Access | Cloudflare edge | human authentication before Open WebUI |
| Chat Cloudflare Tunnel | VPS/cloud | publishes the WebUI without opening a public port on the server |
| OpenRouter | remote service | cloud models available even with the Mac offline |
| Local API Cloudflare Access | Cloudflare edge | machine-to-machine authentication with a Service Token |
| Local API Cloudflare Tunnel | Mac | forwards only the Qwen endpoint to the cloud Open WebUI |
| `qwen38-official` | Mac | local inference on `127.0.0.1:8084` |

### 2.2 Double authentication on the local endpoint

Every request from the VPS to Qwen will carry two independent credentials:

```text
CF-Access-Client-Id / CF-Access-Client-Secret
    → authorises the VPS in Cloudflare Access

Authorization: Bearer <QWEN_API_KEY>
    → authorises inference on qwen38-official itself
```

Open WebUI `v0.11.0` supports a Bearer API key and custom headers per OpenAI-compatible connection. The backend of that version first creates `Authorization: Bearer <API key>` and then appends the custom headers map; therefore, both mechanisms coexist as long as the custom headers do not override `Authorization`.

---

## 3. Availability matrix

| State | Interface/history | OpenRouter | Local Qwen |
|---|:---:|:---:|:---:|
| VPS and Mac online | yes | yes | yes |
| Mac off or without internet | **yes** | **yes** | no |
| `qwen38-official` stopped, Mac tunnel online | yes | yes | no; origin returns an error |
| Mac tunnel stopped, model online | yes | yes | not remotely; still reachable on the Mac itself |
| VPS/Open WebUI stopped | no | not through this UI | Qwen remains usable locally on the Mac |
| Cloudflare unavailable | not through the public domain | not through the public UI | Qwen remains local on the Mac |

To keep an offline local connection from making the model list slow:

- register `qwen38-official-omlx` in **Model IDs (Filter)** instead of relying on `/models` at every load;
- use a short timeout for model discovery;
- keep an OpenRouter model as the default;
- point Open WebUI auxiliary models/tasks at a remote model, not at the home Qwen.

With a manual filter, the Qwen name may still appear while the Mac is offline; selecting the model will produce a connection error. That is expected and preferable to blocking the whole interface.

---

## 4. Requirements and decisions before installation

### 4.1 Accounts and infrastructure

- `seudominio.com` domain active on Cloudflare, with the zone in **Active** status;
- public delegation verified on 25/08/2026: `jacob.ns.cloudflare.com` and `connie.ns.cloudflare.com`;
- `chat.seudominio.com` and `llm-home.seudominio.com` with no conflicting public records in that same check;
- Cloudflare Zero Trust account;
- Linux VPS with Docker Engine and Docker Compose v2;
- SSH or console access to the VPS;
- OpenRouter account and API key with a spend limit;
- Mac connected to the internet whenever the local Qwen is needed.

### 4.2 Hostnames defined for `seudominio.com`

```text
chat.seudominio.com      → Open WebUI cloud, human access
llm-home.seudominio.com  → qwen38-official API, Service Token access only
```

The apex `seudominio.com` and `www.seudominio.com` stay free for a site, redirects or future use. This also avoids mixing WebUI cookies and policies with other services on the domain.

The e-mail allowed in Cloudflare Access **does not need** to end in `@seudominio.com`; use the exact address of your real identity in the IdP/OTP. In the public query of 25/08/2026, the domain published no MX, so do not assume that mail delivery to `@seudominio.com` already exists. Do not reuse the same hostname or the same Access application for human UI and machine-to-machine API. The policies and the risks are different.

### 4.3 Initial VPS capacity

Because inference happens on OpenRouter or on the Mac, the VPS needs no GPU. For a personal instance, a practical starting point is:

- 2 vCPU;
- 4 GB of RAM;
- 30 GB or more of local SSD;
- a single replica/worker.

These numbers are an operational recommendation, not a hard official requirement. Uploads, RAG, multiple users and large vector stores demand more capacity.

### 4.4 Persistence

For personal use with one replica and local SSD, the default Open WebUI SQLite is acceptable according to the official documentation. For multiple replicas or higher load, use PostgreSQL and Redis.

This guide uses:

- one replica;
- SQLite on a persistent volume;
- short JWT;
- Cloudflare Access in front.

Redis is optional but recommended if sessions must be revoked immediately. Without Redis, logout/password change does not revoke an already issued JWT; it stays valid until `JWT_EXPIRES_IN` expires.

---

## 5. Phase 1 — prepare the VPS

> The commands are templates. Replace user, registry and paths. The hostnames `chat.seudominio.com` and `llm-home.seudominio.com` are already the defined ones. Pin versions/digests again on deployment day.

### 5.1 Directory structure

```bash
sudo mkdir -p /opt/open-webui/{data,secrets,backups}
sudo chown -R "$USER":"$USER" /opt/open-webui
chmod 700 /opt/open-webui /opt/open-webui/data \
  /opt/open-webui/secrets /opt/open-webui/backups
cd /opt/open-webui
umask 077
```

### 5.2 Generate a persistent key

```bash
umask 077
printf 'WEBUI_SECRET_KEY=%s\n' "$(openssl rand -hex 32)" \
  > /opt/open-webui/secrets/open-webui.env
chmod 600 /opt/open-webui/secrets/open-webui.env
```

This key signs sessions and protects some supported sensitive data, but it **does not generically encrypt the API keys and custom headers of OpenAI-compatible connections**. On `v0.11.0`, those credentials remain recoverable from the configuration persisted in the database; protect disk, snapshots and backups as secrets. The key must:

- stay the same across container recreations;
- be included in the encrypted backup;
- never enter Git;
- be rotated only with planning, since rotation invalidates sessions.

### 5.3 Build and pin a non-root image

The official `v0.11.0` image runs as UID 0 by default. The Dockerfile supports build `UID`/`GID`. Before publishing, build the reviewed tag from the source release, using the UID/GID of the deploy user:

```bash
cd /opt/open-webui
OPENWEBUI_UID="$(id -u)"
OPENWEBUI_GID="$(id -g)"
git clone --branch v0.11.0 --depth 1 \
  https://github.com/open-webui/open-webui.git source-v0.11.0
cd source-v0.11.0
git rev-parse HEAD

docker build \
  --build-arg UID="$OPENWEBUI_UID" \
  --build-arg GID="$OPENWEBUI_GID" \
  -t local/open-webui:v0.11.0-nonroot .

docker image inspect local/open-webui:v0.11.0-nonroot \
  --format 'user={{.Config.User}} image-id={{.Id}}'
```

Scan the image. For an immutable reference, publish it to a private registry and obtain the `RepoDigest`; without a registry, record/verify the image ID before every deploy and never rebuild the same tag silently. The recommended path uses a digest.

Create `/opt/open-webui/.env` **without secrets**:

```dotenv
OPENWEBUI_IMAGE=<PRIVATE_REGISTRY>/open-webui-nonroot@sha256:<APPROVED_DIGEST>
CLOUDFLARED_IMAGE=cloudflare/cloudflared@sha256:<APPROVED_DIGEST>
OPENWEBUI_UID=1000
OPENWEBUI_GID=1000
```

Replace UID/GID with the values from `id -u`/`id -g` and fix the ownership:

```bash
chown -R "$(id -u):$(id -g)" /opt/open-webui/data
chmod 700 /opt/open-webui/data
chmod 600 /opt/open-webui/.env
```

The bootstrap can be rehearsed with the official image while the port is exclusively on loopback, but **do not publish the hostname before the non-root image, the digest and the controls below pass**.

### 5.4 Initial Open WebUI Compose

Example for the stable version verified on the date of this document:

```yaml
# /opt/open-webui/compose.yaml
services:
  open-webui:
    image: "${OPENWEBUI_IMAGE:?set OPENWEBUI_IMAGE with an approved digest}"
    user: "${OPENWEBUI_UID:?set OPENWEBUI_UID}:${OPENWEBUI_GID:?set OPENWEBUI_GID}"
    container_name: open-webui
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:8080"
    volumes:
      - ./data:/app/backend/data
    env_file:
      - ./secrets/open-webui.env
    environment:
      ENV: prod
      UVICORN_WORKERS: "1"

      WEBUI_URL: "https://chat.seudominio.com"
      CORS_ALLOW_ORIGIN: "https://chat.seudominio.com"
      DEFAULT_USER_ROLE: pending

      ENABLE_PASSWORD_VALIDATION: "true"
      PASSWORD_VALIDATION_REGEX_PATTERN: "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[^\\w\\s]).{12,}$"
      PASSWORD_VALIDATION_HINT: "Minimum 12 characters with uppercase, lowercase, number and symbol."
      JWT_EXPIRES_IN: "4h"

      # Local bootstrap over SSH/HTTP: keep false only until the admin exists.
      # Before publishing the HTTPS hostname, change both values to "true"
      # and recreate the container; this is a mandatory Phase 2 gate.
      WEBUI_SESSION_COOKIE_SECURE: "false"
      WEBUI_SESSION_COOKIE_SAME_SITE: strict
      WEBUI_AUTH_COOKIE_SECURE: "false"
      WEBUI_AUTH_COOKIE_SAME_SITE: strict

      HSTS: "max-age=31536000;includeSubDomains"
      XFRAME_OPTIONS: DENY
      XCONTENT_TYPE: nosniff
      REFERRER_POLICY: strict-origin-when-cross-origin
      PERMISSIONS_POLICY: "camera=(),microphone=(),geolocation=()"

      ENABLE_OPENAI_API_PASSTHROUGH: "false"
      ENABLE_DIRECT_CONNECTIONS: "false"
      ENABLE_COMMUNITY_SHARING: "false"
      ENABLE_PLUGINS: "false"
      ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS: "false"
      ENABLE_CODE_EXECUTION: "false"
      ENABLE_CODE_INTERPRETER: "false"
      ENABLE_WEB_SEARCH: "false"
      ENABLE_AUTOMATIONS: "false"
      ENABLE_SUBAGENTS: "false"
      ENABLE_IMAGE_GENERATION: "false"
      ENABLE_RAG_LOCAL_WEB_FETCH: "false"
      ENABLE_PROFILE_IMAGE_URL_FORWARDING: "false"
      ENABLE_API_KEYS: "false"

      RAG_FILE_MAX_SIZE: "25"
      RAG_FILE_MAX_COUNT: "5"
      RAG_ALLOWED_FILE_EXTENSIONS: ".pdf,.txt,.md,.docx,.csv"

      AUDIT_LOG_LEVEL: METADATA
      ENABLE_AUDIT_LOGS_FILE: "true"
      LOG_FORMAT: json
      GLOBAL_LOG_LEVEL: INFO

      AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST: "5"
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    pids_limit: 512
    mem_limit: 6g
    cpus: 3.0
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

Notes:

- Port 3000 is published only on the VPS loopback; do not open `0.0.0.0:3000`.
- `v0.11.0` was the current stable version consulted on 20/08/2026. Before installing, review releases and pin the approved version or digest.
- Some options are `ConfigVar`: after the first start, changes made in the Admin Panel may prevail over external variables. Verify the effective state after every change.
- Do not use `WEBUI_AUTH=false` on an exposed instance.
- The policy above disables tools/plugins, code execution, web search and automations until there is an explicit need and a security review.
- `user`, `cap_drop`, `no-new-privileges` and limits reduce the blast radius. The non-root build and the volume ownership must be validated with login, migrations, upload, audit and backup. Do not add `read_only` without testing, since startup writes to internal paths.
- The CPU/RAM/PID limits are starting points for a personal VPS; adjust with telemetry. `json-file` rotation prevents unbounded growth of the container logs.
- A full CSP was not imposed in the example because a wrong policy can break the frontend. Test it in report-only first if you decide to add it.

### 5.5 Start only the WebUI

```bash
cd /opt/open-webui
docker compose up -d open-webui
docker compose ps
docker compose logs --tail=100 open-webui
```

### 5.6 Create the first administrator without public exposure

On your administrative machine:

```bash
ssh -N -L 3000:127.0.0.1:3000 usuario@IP_DA_VPS
```

Open:

```text
http://127.0.0.1:3000
```

Steps:

1. create the first user — it becomes the administrator;
2. use a long, unique password stored in a password manager;
3. confirm in the Admin Panel that signup is disabled;
4. confirm `DEFAULT_USER_ROLE=pending`;
5. do not configure tools, functions, code interpreter or web search yet;
6. test logout/login.

The current version disables signup automatically after the first user, but this must be verified in the effective state.

> **Gate before Phase 2:** change `WEBUI_SESSION_COOKIE_SECURE` and `WEBUI_AUTH_COOKIE_SECURE` to `"true"`, run `docker compose up -d --force-recreate open-webui` and start using only the HTTPS hostname. `Secure` cookies do not work in the local HTTP bootstrap; that is why the example starts temporarily at `false`.

---

## 6. Phase 2 — protect and publish Open WebUI

### 6.1 Configure identity in Cloudflare Access

In **Zero Trust → Settings/Access controls → Authentication → Login methods**:

- configure Google/GitHub/OIDC with MFA/passkey; or
- use One-time PIN by e-mail for a simpler setup.

When using OTP, the policy must restrict the **exact e-mail**. Do not create a “Login Method = One-time PIN” policy without an e-mail restriction, since that can allow any valid address.

### 6.2 Create the Access application before the route

In **Zero Trust → Access controls → Applications**:

```text
Type:             Self-hosted and private / public hostname
Hostname:         chat.seudominio.com
Policy:           Allow
Include:          Emails → <YOUR_EXACT_EMAIL_IN_IDP>
Session duration: 12h or 24h
MFA:              enabled in the IdP, if available
```

Cloudflare Access is deny-by-default: only users matching an Allow policy get through. Replace `<YOUR_EXACT_EMAIL_IN_IDP>` with the literal address used in Google/GitHub/OIDC/OTP; do not use a placeholder in the real policy.

Do not use:

- `Include Everyone`;
- `Login Methods: One-time PIN` alone;
- permanent Bypass policy;
- unnecessary e-mail wildcard.

### 6.3 Create the VPS Tunnel

Pre-check in the dashboard:

```text
Websites → seudominio.com → Overview → Status: Active
SSL/TLS → Universal SSL: Active
```

Do not create `A` or `AAAA` DNS records pointing at the VPS manually. When you save the Published application route, the Tunnel creates/manages the corresponding proxied record for `chat.seudominio.com`. If a record with that name already exists, resolve the conflict first.

In **Cloudflare → Networking → Tunnels**:

```text
Create tunnel
Name: openwebui-cloud
Type: cloudflared
Environment: Docker
```

Copy the token once into a private file without putting it in the history:

```bash
cd /opt/open-webui
umask 077
read -r -s TUNNEL_TOKEN
printf '%s' "$TUNNEL_TOKEN" > secrets/cloudflare-ui-tunnel.token
unset TUNNEL_TOKEN
chmod 600 secrets/cloudflare-ui-tunnel.token
```

### 6.4 Add `cloudflared` to Compose

```yaml
# add under services:
  cloudflared:
    image: "${CLOUDFLARED_IMAGE:?set CLOUDFLARED_IMAGE with an approved digest}"
    container_name: cloudflared-open-webui
    restart: unless-stopped
    depends_on:
      - open-webui
    command:
      - tunnel
      - --no-autoupdate
      - run
      - --token-file
      - /run/secrets/tunnel_token
    secrets:
      - tunnel_token
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    pids_limit: 128
    mem_limit: 256m
    cpus: 1.0
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

# add at the root level:
secrets:
  tunnel_token:
    file: ./secrets/cloudflare-ui-tunnel.token
```

The placeholders `${OPENWEBUI_IMAGE}` and `${CLOUDFLARED_IMAGE}` must contain references by **immutable digests**, for example:

```dotenv
OPENWEBUI_IMAGE=<PRIVATE_REGISTRY>/open-webui-nonroot@sha256:<APPROVED_DIGEST>
CLOUDFLARED_IMAGE=cloudflare/cloudflared@sha256:<APPROVED_DIGEST>
```

Record version, digest, approval date and scanner result. In containers, upgrading means deliberately swapping the digest; `--no-autoupdate` prevents updates inside the container.

Start:

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 cloudflared
```

### 6.5 Create the published application route

On the `openwebui-cloud` Tunnel:

```text
Route type:  Published application
Hostname:    chat.seudominio.com
Service URL: http://open-webui:8080
```

In **Additional application settings**, enable **Protect with Access** and select/configure the matching application. This makes `cloudflared` validate the Access JWT before forwarding to the origin.

### 6.6 Tests of the public WebUI

With 4G/5G on your phone:

1. open `https://chat.seudominio.com`;
2. confirm the Cloudflare Access screen;
3. authenticate with the allowed e-mail;
4. confirm the separate Open WebUI login;
5. test logout/login;
6. open in an anonymous tab and confirm that Access appears again;
7. try another e-mail and confirm denial.

Negative network test:

```bash
# From the internet, this should not answer:
curl http://IP_PUBLICO_DA_VPS:3000
```

The VPS must block unnecessary ports in the firewall/security group. WebUI access must happen only through the Tunnel.

---

## 7. Phase 3 — configure OpenRouter

### 7.1 Create a dedicated key

On OpenRouter:

1. create an API key exclusive to this instance;
2. set a credit/spend limit;
3. do not use the account's main key;
4. store it only in Open WebUI/secret manager;
5. rotate it if exposure is suspected;
6. review retention, logging and training use for each selected provider — OpenRouter is a router, and the effective policy also depends on the final provider.

### 7.2 Add the connection

In Open WebUI:

```text
Admin Settings → Connections → OpenAI → Add Connection
```

Fill in:

```text
URL:       https://openrouter.ai/api/v1
API Key:   sk-or-...
Prefix ID: openrouter          # recommended to avoid collisions
```

In **Model IDs (Filter)**, add only the models you want. OpenRouter exposes thousands of models; loading everything pollutes the selector and makes the panel slower.

Example IDs must be confirmed in the current OpenRouter catalogue before registering. Do not copy old IDs without checking availability and price.

### 7.3 Default model and auxiliary tasks

So that Open WebUI stays functional while the Mac is offline:

- pick an OpenRouter model as the default model;
- pick a cheap/fast remote model for titles, tags and other auxiliary tasks;
- do not use `qwen38-official-omlx` as the only default model;
- keep a small allowlist.

### 7.4 Mac-independence test

Before integrating the home Qwen:

1. stop/power off the Mac;
2. access the WebUI from the phone;
3. create a chat with an OpenRouter model;
4. confirm streaming and history persistence;
5. restart the WebUI and confirm data and login.

This test shows that continuity comes from real hosting on the VPS, not from the Tunnel.

---

## 8. Phase 4 — publish only the minimal local Qwen API

This phase changes the model's exposure posture: the service stays on loopback, but gains a public hostname protected by two authentications. Do it only after validating Open WebUI and OpenRouter.

### 8.1 Preconditions on the Mac

First complete the clean-room guide, including cryptographic verification, the MTP smoke test and the real 40000-token canary. Only then:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
qwen38-official verify
qwen38-official start
qwen38-official status
lsof -nP -iTCP:8084 -sTCP:LISTEN
"$PROFILE/runtime/venv/bin/python" "$PROFILE/context-canary.py" \
  --prompt-tokens 40000 --max-tokens 4 --require-mtp
```

The listener must stay:

```text
127.0.0.1:8084
```

Never change it to:

```text
0.0.0.0:8084
```

The Tunnel connects to loopback as a local process; there is no need to open a firewall or router.

### 8.2 Create a Service Token for the VPS

In:

```text
Zero Trust → Access controls → Service credentials → Service Tokens
```

Create:

```text
Name:     openwebui-cloud-to-qwen-home
Duration: defined and reviewable; set an alert before expiry
```

Save immediately:

- Client ID;
- Client Secret.

The secret appears only once. Store it in the secret manager and never in Git.

### 8.3 Create the Access application for the local API

Create it before the public route:

```text
Type:      Self-hosted
Hostname:  llm-home.seudominio.com
Action:    Service Auth
Include:   Service Token → openwebui-cloud-to-qwen-home
401 for Service Auth: enabled
```

Do not add a human Allow policy, `Everyone` or Bypass on this hostname. The API was designed for a single service identity.

### 8.4 Create the Tunnel on the Mac

As with the chat hostname, do not create `A`/`AAAA` pointing at the residential IP. The Tunnel's Published application route manages the proxied DNS for `llm-home.seudominio.com`; remove or rename any conflicting record before saving.

```text
Networking → Tunnels → Create tunnel
Name: qwen-home
Type: cloudflared
System: macOS arm64
```

The route will be created after the Access application:

```text
Hostname:    llm-home.seudominio.com
Service URL: http://127.0.0.1:8084
Protect with Access: enabled
```

### 8.5 Run `cloudflared` on the Mac

#### Mandatory path: token in a file

Do not run the command copied from the dashboard with the literal token. It can end up in the history and in the process `argv`. Extract the token through the interface only to write it straight into an owner-only file — no echo, screenshot or literal command line — and then close/clear the clipboard.

Use `cloudflared >= 2025.4.0` with `--token-file`, keeping the token in a `0600` file, plus a user LaunchAgent. This keeps the literal token out of the process arguments.

Suggested layout:

```text
~/.config/cloudflared-qwen/tunnel.token           mode 0600
~/Library/LaunchAgents/com.local.cloudflared-qwen.plist
~/Library/Logs/cloudflared-qwen.{out,err}.log
```

Example `ProgramArguments` in the LaunchAgent:

```xml
<array>
  <string>/opt/homebrew/bin/cloudflared</string>
  <string>tunnel</string>
  <string>--loglevel</string>
  <string>info</string>
  <string>run</string>
  <string>--token-file</string>
  <string>/Users/SEU_USUARIO/.config/cloudflared-qwen/tunnel.token</string>
</array>
```

Use the path returned by `command -v cloudflared`; do not assume `/opt/homebrew/bin` on an Intel Mac or on different installs.

The LaunchAgent starts after user login. That matches the MLX/Metal model, which must also run in the user context. Do not enable automatic login just to start the model.

The `qwen38-official` process has egress blocked by sandbox; this does not prevent the Tunnel, because `cloudflared` is another process that receives connections from Cloudflare and calls `127.0.0.1:8084` locally.

### 8.6 Logs

Keep `cloudflared` at `info`. Do not use `debug` continuously: the documentation warns that debug logs URL, method and headers, and can expose credentials.

---

## 9. Phase 5 — connect the cloud Open WebUI to Qwen

### 9.1 Test both authentications outside the WebUI

On the VPS, write the three values into `0600` files via secret manager or silent input; do not use `export SEGREDO='...'`, since that can go to the history. For the test, use a temporary `0600` config file and pass only its path to `curl`, keeping secret headers out of `argv`:

```bash
umask 077
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT INT TERM

# These files must come from the secret manager/silent input, never from Git:
CF_ID_FILE=/run/secrets/cf_access_client_id
CF_SECRET_FILE=/run/secrets/cf_access_client_secret
QWEN_KEY_FILE=/run/secrets/qwen_api_key

{
  printf 'silent\nshow-error\nfail-with-body\n'
  printf 'url = "https://llm-home.seudominio.com/v1/models"\n'
  printf 'header = "CF-Access-Client-Id: %s"\n' "$(<"$CF_ID_FILE")"
  printf 'header = "CF-Access-Client-Secret: %s"\n' "$(<"$CF_SECRET_FILE")"
  printf 'header = "Authorization: Bearer %s"\n' "$(<"$QWEN_KEY_FILE")"
} > "$TEST_DIR/positive.curlrc"
chmod 600 "$TEST_DIR/positive.curlrc"
curl --config "$TEST_DIR/positive.curlrc"
```

It must return `qwen38-official-omlx`. Do not use `set -x`, do not print the file and confirm that logs/`ps` do not contain the values.

Negative tests use the same pattern and new temporary files:

```bash
# Without a Service Token: must be denied at Cloudflare Access.
{
  printf 'silent\nshow-error\ninclude\n'
  printf 'url = "https://llm-home.seudominio.com/v1/models"\n'
  printf 'header = "Authorization: Bearer %s"\n' "$(<"$QWEN_KEY_FILE")"
} > "$TEST_DIR/no-access-token.curlrc"
curl --config "$TEST_DIR/no-access-token.curlrc"

# With a Service Token but without the Qwen Bearer: must be denied at the origin.
{
  printf 'silent\nshow-error\ninclude\n'
  printf 'url = "https://llm-home.seudominio.com/v1/models"\n'
  printf 'header = "CF-Access-Client-Id: %s"\n' "$(<"$CF_ID_FILE")"
  printf 'header = "CF-Access-Client-Secret: %s"\n' "$(<"$CF_SECRET_FILE")"
} > "$TEST_DIR/no-qwen-key.curlrc"
curl --config "$TEST_DIR/no-qwen-key.curlrc"
```

The `trap` removes the temporary files. In an environment with untrusted other users/root, run them on a private tmpfs or directly in the secret manager. If any token was ever typed literally in a command, treat it as exposed and rotate the Tunnel Token, the Service Token and the Qwen key.

### 9.2 Configure the connection in Open WebUI

In the Admin Panel:

```text
Admin Settings → Connections → OpenAI → Add Connection
```

Fields:

```text
URL:       https://llm-home.seudominio.com/v1
API Key:   contents of ~/models/qwen38-official-omlx/state/api-key on the Mac
Prefix ID: local                         # yields local.qwen38-official-omlx
Model IDs (Filter): qwen38-official-omlx  # recommended
```

In **Advanced / Custom Headers**:

```json
{
  "CF-Access-Client-Id": "<CLIENT_ID>",
  "CF-Access-Client-Secret": "<CLIENT_SECRET>"
}
```

Do not put `Authorization` in Custom Headers. The **API Key** field already produces:

```text
Authorization: Bearer <QWEN_API_KEY>
```

The manual filter avoids a continuous `/models` query while the Mac is offline. With the normative prefix `local`, the ID in the selector/workspace is `local.qwen38-official-omlx`, the same one used by the clean-room guide's compaction. If you change the prefix, also update the workspace model, the ACL and `CONTEXT_COMPACTION_MODEL`.

### 9.3 Test streaming

1. select Qwen in Open WebUI;
2. send a short prompt;
3. confirm progressive streaming;
4. check `qwen38-official status` on the Mac;
5. verify that the request appears in the log without headers/secrets;
6. test a response long enough to exercise SSE.

The current profile uses SSE keepalive in chunks. This helps avoid an inactivity timeout; very long prompts should still be tested, because a TTFT with no chunks for too long can hit proxy limits.

---

## 10. Behaviour when the Mac is offline

### 10.1 Functional failover test

1. leave Open WebUI/VPS online;
2. stop the model:
   ```bash
   qwen38-official stop
   ```
3. optionally stop the Mac Tunnel;
4. reload `https://chat.seudominio.com`;
5. confirm that login, history and OpenRouter work;
6. select Qwen and confirm a controlled error;
7. start the model and the Tunnel again;
8. confirm that a new Qwen conversation works.

### 10.2 What does not exist automatically

Open WebUI does not turn `qwen38-official-omlx` into OpenRouter when it goes offline. For automatic fallback of the same alias you would need:

- a gateway such as LiteLLM;
- an explicit routing rule;
- semantically replaceable models;
- a cost and privacy policy.

For the first version, prefer explicit model selection. It is simpler and avoids inadvertently sending a private prompt to a remote provider.

---

## 11. Mandatory hardening

### 11.1 Cloudflare

- create the Access application before each route;
- UI: Allow only the exact e-mail/IdP;
- API: Service Auth only for the specific token;
- enable **Protect with Access** on both origins;
- never use permanent Bypass;
- set an alert for Service Token expiry;
- review Access logs;
- apply rate limiting/WAF where the plan allows;
- do not publish the residential IP or ports 3000/8084;
- revoke the Tunnel token or Service Token immediately if it leaks.

### 11.2 Open WebUI

- keep the version pinned;
- one replica/worker while using SQLite;
- signup closed after the admin;
- strong password and Cloudflare Access in front;
- short JWT or Redis for revocation;
- Secure/SameSite cookies;
- CORS only for the real domain;
- `ENABLE_OPENAI_API_PASSTHROUGH=false`;
- `ENABLE_DIRECT_CONNECTIONS=false`;
- plugins, automatic pip, code, tools and web search off until reviewed;
- dedicated OpenRouter key with a spend limit;
- allowlist of models and providers whose retention/training policy is acceptable;
- explicit retention policy for chats, uploads, Access logs, audit logs and backups;
- audit logs only `METADATA` so prompts/answers are not recorded;
- upload/CPU/RAM/PID limits, log rotation and a disk alert before 80%;
- protect the data directory and secrets.

### 11.3 Mac/Qwen

- keep `127.0.0.1:8084`;
- keep Bearer authentication;
- do not widen the minimal facade;
- keep egress denied;
- do not enable MCP, remote code, web, tools or model mutation;
- keep concurrency at 1 or set a compatible rate limit;
- preserve the `qwen38-official-omlx` directory itself and the coherent operational rollback at `32768` documented in the clean-room guide;
- run `qwen38-official verify --quick` before starting and the full verification after install/restore;
- do not copy the API key into documents, chat or screenshots.

### 11.4 Secrets on the VPS

The VPS/Open WebUI will store — including in persisted configuration recoverable from the database —:

- OpenRouter API key;
- Qwen Bearer key;
- Cloudflare Access Client ID/Secret;
- WebUI secret key;
- VPS Tunnel token.

A root administrator of the VPS can reach that data. Use:

- trusted cloud vendor;
- encrypted disk where available;
- `0600` files, `0700` directories and disk/snapshot encryption where available;
- encrypted backups;
- separate, rotatable keys;
- no credentials in Git or in a public Compose.

If Open WebUI is compromised, revoke:

1. the `openwebui-cloud-to-qwen-home` Service Token;
2. the Qwen API key;
3. the OpenRouter API key;
4. Open WebUI sessions/key as the impact requires.

---

## 12. Privacy and data flow

### OpenRouter

When selecting OpenRouter:

```text
Phone → Cloudflare → VPS/Open WebUI → OpenRouter → chosen provider
```

The prompt leaves your infrastructure and is subject to the policies of OpenRouter and of the chosen provider.

### Local Qwen

When selecting Qwen:

```text
Phone → Cloudflare → VPS/Open WebUI → Cloudflare → Tunnel → Mac/Qwen
```

The weights and the inference stay on the Mac, but:

- the prompt goes through the VPS;
- TLS is terminated/processed in Cloudflare's infrastructure;
- history is stored on the VPS/Open WebUI;
- the VPS provider controls the host and can, technically, access memory/disk.

If the requirement is that neither Cloudflare nor the VPS can observe plaintext prompts, this architecture does not meet it; a different trust model would be needed, typically a VPN or end-to-end application encryption.

---

## 13. Backup, upgrade and rollback

### 13.1 Backup

The `/app/backend/data` directory holds the database, users, chats, uploads, settings and connection credentials. **The whole backup must be encrypted**, not just `secrets/`. Do not keep plaintext `.tar.gz`. Prefer `restic` or `borg`; another option is streaming `tar` straight into `age`. The example assumes the DB is at `data/webui.db`; confirm the path in the deployed release before automating:

```bash
cd /opt/open-webui
set -euo pipefail
umask 077
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/opt/open-webui/backups/open-webui-$STAMP.tar.gz.age"
PARTIAL="$BACKUP.partial"
RECIPIENT='age1SUBSTITUA_PELA_CHAVE_PUBLICA_DO_BACKUP'
IDENTITY='/CAMINHO/PRIVADO/backup-identity.txt'

RESTORE_CHECK="$(mktemp -d)"
restart_webui() { docker compose start open-webui >/dev/null || true; }
cleanup() { rm -f "$PARTIAL"; rm -rf "$RESTORE_CHECK"; restart_webui; }
trap cleanup EXIT INT TERM

docker compose stop open-webui
tar -C /opt/open-webui -czf - data secrets \
  | age -r "$RECIPIENT" -o "$PARTIAL"
age -d -i "$IDENTITY" "$PARTIAL" | tar -tzf - \
  | grep -qE '(^|/)data/webui\.db$'
age -d -i "$IDENTITY" "$PARTIAL" \
  | tar -xzf - -C "$RESTORE_CHECK" data/webui.db
test "$(sqlite3 "$RESTORE_CHECK/data/webui.db" 'PRAGMA integrity_check;')" = 'ok'
mv "$PARTIAL" "$BACKUP"
sha256sum "$BACKUP" > "$BACKUP.sha256"
rm -rf "$RESTORE_CHECK"
docker compose start open-webui
trap - EXIT INT TERM
```

The backup private key must live outside the VPS. Define and record:

- daily backup and before every upgrade;
- suggested initial retention: 7 daily, 4 weekly and 6 monthly;
- initial RPO of 24 h and RTO of 2 h, adjusted to need;
- failure alert;
- quarterly restore test on an isolated volume/instance;
- expiry policy so that expired backups do not reintroduce already deleted chats.

Do not treat the VPS disk itself as a backup. Copy the encrypted files to independent storage with versioning.

### 13.2 Retention and privacy policy

Before go-live, record an explicit decision, for example:

| Data | Initial retention | Access |
|---|---:|---|
| Chats/uploads | until user deletion or 90 days | user and root-equivalent admin |
| `METADATA` audit log | 30 days | administrator |
| Cloudflare Access logs | per plan, review in the dashboard | Cloudflare administrators |
| Daily backups | 7 daily + 4 weekly + 6 monthly | operator holding the `age` key |

The table is a starting point, not a legal obligation. Adapt it to the content and the jurisdiction. Test deletion and make sure that backup expiry does not reintroduce deleted data. For OpenRouter, record the approved providers and their retention/training policies.

### 13.3 Upgrade

1. review release notes;
2. create a consistent backup and prove that it decrypts/lists;
3. keep `UVICORN_WORKERS=1` during migrations;
4. switch to the new approved digest;
5. `docker compose pull`;
6. `docker compose up -d`;
7. verify logs, login, history, OpenRouter and Qwen;
8. only then remove the old image and, after the defined retention, the previous backup.

Database migrations can be one-way. Rolling back the image alone may not work; the real rollback may require restoring the previous backup.

### 13.4 Restore and version rollback

Testable procedure:

1. stop Open WebUI and keep the failed state with a timestamp, without overwriting it;
2. create an empty restore volume/directory;
3. verify SHA-256 and decrypt the backup straight into that destination;
4. restore `data` and the set of secrets matching the same date;
5. configure the old image by the **digest** preserved alongside the backup;
6. start a single replica/worker;
7. validate login, history, OpenRouter, custom headers and Qwen;
8. only then promote the restored directory and archive the failed state.

Test this runbook on a separate instance before depending on it. An old image with an already migrated database is not a rollback; both must return to the same compatible point.

### 13.5 Local access rollback

To remove Qwen from the cloud without affecting the local model:

1. disable/remove the connection in Open WebUI;
2. revoke the Service Token;
3. remove the `llm-home.seudominio.com` route;
4. stop/disable the Mac `cloudflared`.

`qwen38-official` keeps working locally on `127.0.0.1:8084`; removing the Tunnel neither removes nor changes the profile.

---

## 14. Observability and operation

### VPS

```bash
cd /opt/open-webui
docker compose ps
docker compose logs --tail=100 open-webui
docker compose logs --tail=100 cloudflared
```

### Mac

```bash
qwen38-official status
qwen38-official logs
lsof -nP -iTCP:8084 -sTCP:LISTEN
```

### Cloudflare

Check:

- Tunnel `openwebui-cloud`: Healthy;
- Tunnel `qwen-home`: Healthy while the Mac is online;
- UI Access logs;
- Service Auth Access logs;
- Service Token expiry;
- failures and abnormal request volume.

Do not record prompt bodies in audit logs. `METADATA` is enough for the first rollout.

---

## 15. Acceptance checklist

### Open WebUI cloud

- [ ] containers use approved, recorded `sha256` digests;
- [ ] persistent volume exists;
- [ ] WebUI secret is protected and backed up;
- [ ] first account is admin;
- [ ] signup is disabled;
- [ ] port 3000 is only on `127.0.0.1` on the VPS;
- [ ] Cloudflare Access requires the correct e-mail;
- [ ] unauthorised user is denied;
- [ ] after bootstrap, both cookies are `Secure=true` and CORS is restricted;
- [ ] plugins, code, tools and passthrough are off;
- [ ] upload/CPU/RAM/PID limits and log rotation are in effect;
- [ ] backup is encrypted, has retention/RPO/RTO and restore was tested.

### OpenRouter

- [ ] key is exclusive and has a spend limit;
- [ ] small model allowlist;
- [ ] remote model is the default;
- [ ] works with the Mac off;
- [ ] costs and data policies were reviewed.

### Remote local Qwen

- [ ] clean-room guide for `fcmeyer@0299356…` was completed;
- [ ] cryptographic `qwen38-official verify` passes;
- [ ] smoke records Lightning MTP active and the 40K canary passes;
- [ ] `qwen38-official verify --quick` passes on every start;
- [ ] listener stays on `127.0.0.1:8084`;
- [ ] Access app uses Service Auth, not Allow/Bypass;
- [ ] Service Token is specific and has an expiry alert;
- [ ] Protect with Access is enabled;
- [ ] request without a Service Token is denied;
- [ ] request without the Qwen Bearer is denied;
- [ ] request with both returns `/v1/models`;
- [ ] chat through the WebUI streams;
- [ ] Mac offline does not take OpenRouter/WebUI down;
- [ ] no secret appears in logs or processes.

---

## 16. Recommended deployment sequence

1. choose VPS, domain and hostnames;
2. install Docker/Compose on the VPS;
3. start Open WebUI pinned, only on loopback;
4. create the admin over an SSH tunnel and close signup;
5. create the human Access application;
6. create the VPS Tunnel and publish only the WebUI;
7. test mobile access and denials;
8. configure OpenRouter and prove it works with the Mac off;
9. create the Service Token and the Access application for the local API;
10. create the Mac Tunnel to `127.0.0.1:8084`;
11. test both authentications with `curl`;
12. add the Qwen connection with custom headers and a model filter;
13. test streaming and offline behaviour;
14. configure backup, alerts and the rotation procedure;
15. only then consider auto-start for the Tunnel and the model.

This order avoids publishing an application without Access and preserves a rollback path at every phase.

---

## 17. Costs and dependencies

| Item | Possible cost |
|---|---|
| Domain | annual |
| VPS | monthly |
| Cloudflare Tunnel/Access | depends on the plan and current limits |
| OpenRouter | per use/model |
| Backup storage | per volume/egress |
| Mac power | while the local model is available |

Do not pin values in this document: prices and limits change. Check the commercial pages on deployment day.

---

## 18. Official references

### Open WebUI

- Quick Start: <https://docs.openwebui.com/getting-started/quick-start/>
- OpenAI-compatible providers: <https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/>
- Hardening: <https://docs.openwebui.com/getting-started/advanced-topics/hardening/>
- Environment variables: <https://docs.openwebui.com/reference/env-configuration/>
- Updating/backup: <https://docs.openwebui.com/getting-started/updating/>
- Releases: <https://github.com/open-webui/open-webui/releases>
- `v0.11.0` backend with Bearer + custom headers: <https://raw.githubusercontent.com/open-webui/open-webui/v0.11.0/backend/open_webui/routers/openai.py>

### Cloudflare

- Create remotely managed Tunnel: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/>
- Publish self-hosted application with Access: <https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/>
- Access policies: <https://developers.cloudflare.com/cloudflare-one/access-controls/policies/>
- Service Tokens: <https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/>
- Protect origin with Access: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/#access>
- Tunnel run parameters/token-file: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/>
- Run cloudflared as macOS service: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/macos/>

### OpenRouter

- Authentication: <https://openrouter.ai/docs/api/reference/authentication>
- API keys: <https://openrouter.ai/keys>

---

## 19. Conclusion

This runbook deliberately uses a VPS because the requirement is to keep Open WebUI and OpenRouter available without the Mac. Cloudflare Tunnel alone does not provide that hosting.

The recommended architecture keeps the interface and the history in the cloud, uses OpenRouter as an always-available path and treats the M3 Max as an intermittent inference provider. The home endpoint opens no port on the router and stays bound to loopback; the VPS reaches it through a Tunnel protected by Service Auth and by Qwen's own API key.

This delivers the desired behaviour:

- phone accesses over HTTPS without a VPN;
- Open WebUI and OpenRouter work with the Mac off;
- the local Qwen appears when the Mac is online;
- the weights never leave the M3 Max;
- each layer can be disabled and revoked independently.
