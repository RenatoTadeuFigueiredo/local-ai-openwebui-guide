# Multi-user browser HITL: architecture, POC, and restricted publication

> **English** · [Português](../pt-br/docs/04-browser-hitl-multi-user-poc.md)

**Status as of 26/08/2026:** local POC validated for admin and user-a; portal published separately at `browser.seudominio.com` with Cloudflare Access/OTP; low-risk mobile E2E still pending  
**Open WebUI:** `0.11.0`  
**POC backend:** Python `3.12`, FastAPI, Playwright `1.62.0`, Chromium `151.0.7922.71`, SQLite, Xvfb, x11vnc and noVNC  
**Goal:** let the agent browse arbitrary sites, pause at login/MFA/CAPTCHA, hand the same tab to the user and resume with the persisted session

> This document describes a **POC published with restricted access**, not an authorization to use high-value accounts. The first mobile test should use a disposable site or a low-impact service. Primary Google, real Gmail, real Drive, banks, healthcare, government and production consoles remain out of the initial scope.
>
> The Model ID `local.qwen38-omlx` cited here belongs to the current uncensored deployment described in [`02-deploy-macos-cloudflare-tunnel.md`](02-deploy-macos-cloudflare-tunnel.md). A migration to the recommended `local.qwen38-official-omlx` profile requires updating connection, ACL, compaction and canaries; the configuration below is not independent evidence of the new checkpoint.

---

## 1. Delivered result

The POC implements:

- a persistent browser identity for admin;
- a separate and persistent identity for user-a;
- binding through the immutable UUID of the account authenticated in Open WebUI;
- Chromium and `user-data-dir` directory separated per user;
- one active session per profile;
- the same window, tab, Chromium process and profile across the handoff;
- a durable lock between agent and human;
- `HTTP 423 Locked` blocking for agent actions and observations during takeover;
- a short takeover link, with the token stored only as a hash in SQLite;
- CSRF, human session cookie and `Origin` verification;
- noVNC started only after the human takes control;
- shutdown of x11vnc/websockify when the human hands control back;
- an explicit `READY_TO_RESUME` return and a new lease before the agent continues;
- persistence of cookies, `localStorage`, IndexedDB and other profile data in the Docker volume;
- an egress proxy that blocks loopback, private networks, link-local, metadata and non-web ports;
- a native Open WebUI Tool visible only to admin and user-a;
- a persisted Rich UI that explains the takeover without returning URL/token to the model context;
- a transient panel created by the Tool itself via the official `execute` event, in the Open WebUI main context, with a **Take over browser** button; the human click opens a clean tab without inheriting the Rich UI sandbox.

The validated flow is:

```text
AGENT_ACTIVE
    │ agent finds login/MFA/CAPTCHA
    ▼
WAITING_FOR_HUMAN
    │ user opens Rich UI and takes over
    ▼
HUMAN_ACTIVE
    │ agent actions and observations return 423
    │ user authenticates in the same tab
    ▼
READY_TO_RESUME
    │ new turn calls browser_resume
    ▼
AGENT_ACTIVE with new epoch
```

---

## 2. Implemented topology

```text
chat.seudominio.com
      │ user authenticated in Open WebUI
      ▼
Native Python Tool: browser_hitl_private
      │ UUID coming from __user__, never from the model
      │ global key encrypted in the Open WebUI Valves
      ▼
127.0.0.1:3210
Browser HITL Broker
      ├── state SQLite + epochs + grants
      ├── persistent profile UUID A → admin
      ├── persistent profile UUID B → user-a
      ├── private Playwright/CDP
      ├── private Xvfb
      ├── x11vnc/noVNC only in HUMAN_ACTIVE
      └── egress proxy with private destination blocking
```

The container publishes only `127.0.0.1:3210` on the Mac. CDP, VNC, websockify, Xvfb and the egress proxy stay internal to the container. The Cloudflare Tunnel forwards exclusively `browser.seudominio.com` to that loopback and the hostname is protected by Access/OTP at the edge and by JWT validation again at the origin; `chat.seudominio.com` remains without Access.

The previous `Computer admin` remains separate and unchanged at `127.0.0.1:3011` and was not published remotely.

---

## 3. Identity and isolation

The Tool receives these values from Open WebUI itself:

- `__user__["id"]`;
- `__user__["name"]`;
- `__user__["role"]`;
- `__metadata__["chat_id"]`.

No method exposes `user_id`, e-mail or profile name as an argument controllable by the model. The Tool converts the authenticated identity into internal headers; the broker validates that identity and filters every object by owner.

Current ACL state:

| User | Tool visible | Can read Valves/secret |
|---|---:|---:|
| admin | yes | yes, because it is root-equivalent |
| user-a | yes | no (`401`) |
| user-b | no | no (`401`) |
| user-c | no | no (`401`) |
| user-d | no | no (`401`) |

Each profile receives:

- an opaque `profile_id`;
- an exclusive internal slot;
- its own directory, mode `0700`;
- its own Chromium process when active;
- independent persistence in the `openwebui-browser-hitl-poc_browser-hitl-poc-data` volume.

The Open WebUI account identifies the **profile owner**. The Google/Facebook/LinkedIn account used inside it will be the one the user itself chooses at takeover.

---

## 4. Login persistence

The Chromium `user-data-dir` lives in:

```text
/data/browser-hitl/profiles/<opaque-profile-id>
```

This directory survives:

- closing the tab;
- the end of the chat;
- broker restart;
- container recreation via Compose;
- Mac restart, as long as the volume is not removed.

So, after admin authenticates into a Google account in their profile, cookies and storage remain in that profile. user-a has another directory and does not receive that data.

Persistence does not mean eternal login. The site may still ask for authentication again due to expiration, corporate policy, risk change, revocation, changed password or automation detection.

> Do not use `docker compose down -v`. The `-v` flag removes the volume and erases the persistent profiles.

---

## 5. Mutual exclusion and epochs

State lives in SQLite with `BEGIN IMMEDIATE`, WAL, `foreign_keys=ON` and compare-and-swap transitions. Each session has a monotonically increasing `epoch`.

Every agent action sends:

- `session_id`;
- current `epoch`;
- authenticated identity, injected by the Tool.

The broker checks the state before the action and again before publishing the result. During `WAITING_FOR_HUMAN` and `HUMAN_ACTIVE`:

- `navigate` fails;
- `snapshot` fails;
- `click` fails;
- `type` fails;
- an old epoch fails;
- the agent receives no screenshot, DOM, page text or network events.

When control is handed back, the state is `READY_TO_RESUME`; there is still no automation. A new turn calls `browser_resume`, which issues another epoch and only then restores `AGENT_ACTIVE`.

If the broker restarts during takeover, it revokes active grants and recovers to `READY_TO_RESUME`, never directly to the agent. On resume, the runtime/Xvfb/Chromium must come up before the durable transition to `AGENT_ACTIVE`; a failure keeps `READY_TO_RESUME` for safe retry. Stale locks and X sockets are removed only after confirming that no X server accepts a connection on that display.

---

## 6. Takeover security

The takeover grant:

- uses 32 random URL-safe bytes;
- can be redeemed for up to five minutes in the POC;
- after redemption, the link deadline does not interrupt an ongoing human authentication; the lock remains until explicit completion or fail-closed recovery;
- is persisted only as SHA-256;
- belongs to a specific `user_id`, `session_id` and `epoch`;
- can be redeemed only once;
- requires `POST`, CSRF and the expected `Origin`/`Referer`; the portal uses `Referrer-Policy: origin`, which preserves only the origin for that validation without leaking the token from the path;
- creates an `HttpOnly`, `SameSite=Strict` cookie;
- is not consumed by `GET` or by link preview;
- is revoked after completion or recovery.

The Tool removes `portal_url` before assembling the result for the LLM. The URL is delivered only to the authenticated frontend `execute` event to build the transient panel; the persisted Rich UI does not contain the token. The context returned to the model contains only `WAITING_FOR_HUMAN` and the instruction to end the turn.

In local HTTP mode, the cookie cannot use `Secure`/the `__Host-` prefix; the POC uses a distinct local name. Before any HTTPS publication, the broker automatically switches to a `__Host-...; Secure` cookie.

The viewer:

- requires a redeemed grant;
- requires a human cookie bound to the grant, user and epoch;
- verifies `Origin` on the WebSocket;
- passes noVNC and the RFB protocol through the broker;
- delivers the ephemeral RFB password automatically in the iframe `#` fragment (not sent in HTTP/Referer), without showing it to the user or to the model;
- does not publish VNC/noVNC ports on the host;
- disables clipboard in both directions;
- shuts down x11vnc and websockify on handback.

---

## 7. Browser and network

Chromium runs without `--no-sandbox`. The container uses:

- non-root user `cptr`;
- `cap_drop: ALL`;
- `no-new-privileges`;
- seccomp validated for Chromium sandbox;
- limit of 768 processes;
- 8 GiB of memory;
- 4 CPUs;
- 1 GiB of `/dev/shm`;
- no Docker socket, Mac `$HOME`, Keychain or `~/.ssh`.

Chromium policies disable:

- Password Manager;
- address autofill;
- card autofill;
- Browser Sign-in;
- Sync;
- metrics;
- geolocation and notifications by default;
- local schemes such as `file:`, `filesystem:`, `chrome:` and `devtools:` (the private loopback CDP required by the agent remains enabled);
- QUIC and non-proxied WebRTC UDP, reducing HTTP proxy bypass paths.

The egress proxy accepts only HTTP/HTTPS on ports 80/443 and rejects:

- `localhost` and `*.localhost`;
- `host.docker.internal`;
- `*.local`;
- IPv4/IPv6 loopback;
- RFC1918;
- IPv6 ULA;
- link-local;
- `169.254.169.254` and other non-global addresses;
- DNS that resolves to any non-global address;
- ports such as SSH, database or internal APIs.

This is a POC control, not a complete corporate firewall.

---

## 8. Code and operational files

Versionable source:

```text
examples/browser-hitl-poc/
├── browser_hitl/
│   ├── api.py
│   ├── egress_proxy.py
│   ├── runtime.py
│   ├── security.py
│   ├── settings.py
│   └── store.py
├── openwebui/browser_hitl_tool.py
├── tests/
├── Dockerfile
├── compose.yaml
├── chromium-policy.json
├── provision_poc.py
├── pyproject.toml
└── .gitignore
```

Local secrets, ignored by Git:

```text
examples/browser-hitl-poc/secrets/
├── tool-api-key
├── admin-api-key
└── portal-signing-key
```

All are mode `0600`. The provisioner does not pass values in `argv`, labels, Docker variables or logs.

Open WebUI was changed to:

```text
ENABLE_PLUGINS=true
ENABLE_VALVE_ENCRYPTION=true
ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS=false
ENABLE_CONTEXT_COMPACTION=true
CONTEXT_COMPACTION_MODEL=local.qwen38-omlx
CONTEXT_COMPACTION_TOKEN_THRESHOLD=245760
CONTEXT_COMPACTION_TOKEN_CAP=245760
CONTEXT_COMPACTION_RETENTION_PERCENTAGE=40
SAFE_MODE=true
```

The persisted permissions of regular users remain:

```text
workspace.tools=false
workspace.tools_import=false
workspace.tools_export=false
sharing.tools=false
sharing.public_tools=false
```

Therefore, enabling the Tools runtime does not grant arbitrary creation/import to regular users. Even so, Python Tools are code execution in the Open WebUI process; only the administrator should register reviewed code.

Since browsing traces can grow quickly, automatic compaction remains active. The checkpoint declares a native maximum of `262144` tokens and oMLX announces the same value; the estimated threshold/cap of `245760` provides a nominal margin of `16384`, not a hard reserve. The facade limits output to `8192`, binds the reduced ceiling to the request before streaming and guarantees `prompt + output <= 262144`; MTP also reduces speculation near the limit using the real cache offsets. Since Tools are injected after the compaction decision, exceptionally large schemas can consume the margin, reduce output or cause rejection — do not anticipate compaction. The configuration is in `env`, in the persisted Config and in the workspace model `compact_token_threshold`. Before the expansion, the chat that reached `34083` tokens was compacted to a `1024`-character checkpoint, keeping its ten visible messages; the estimated active context dropped from `29533` to `260` tokens.

---

## 9. Operation

### State

```bash
cd examples/browser-hitl-poc
docker compose ps
docker logs --tail=100 openwebui-browser-hitl-poc
curl -fsS http://127.0.0.1:3210/health
```

### Opening the takeover outside the sandbox

Open WebUI `0.11.0` renders Rich UI in a sandboxed iframe. A `target="_blank"` link inside that iframe opens a tab that inherits the sandbox; in Chromium this blocked the local portal with `ERR_BLOCKED_BY_RESPONSE`.

The final solution does not change the global frontend nor loosen other embeds. The audited Tool emits the official `execute` event to create a transient panel in the Open WebUI main context. The panel:

- contains only fixed text, the limited reason and the ephemeral URL returned by the broker;
- builds the elements with `createElement`/`textContent`, without `innerHTML` or `eval`;
- uses a `target="_blank"` link with `rel="noopener noreferrer"`;
- opens the tab through a real human click, without an inherited sandbox;
- disappears on reload/navigation, while the persisted Rich UI keeps recording that the takeover was requested;
- does not return the URL to the model.

The previous patch installation in `frontend/index.html` was removed; the global Open WebUI file remains original.

### Idempotent reprovisioning

```bash
cd examples/browser-hitl-poc
./provision_poc.py \
  --user '<UUID_RENATO>' \
  --user '<UUID_GIOVANNA>'
```

The command:

1. creates/reuses local secrets;
2. validates the Compose;
3. brings the broker up;
4. provisions/reuses the profiles;
5. creates/updates the Tool;
6. writes the encrypted Valves;
7. reapplies the exact grants.

### Stop without erasing profiles

```bash
cd examples/browser-hitl-poc
docker compose stop
```

### Restart

```bash
cd examples/browser-hitl-poc
docker compose start
```

The POC uses `restart: "no"` and does not start automatically. This is intentional until the real test and the security review are complete. The Compose has a local broker healthcheck, but a crash still requires manual action at this stage.

### Rollback

To remove the capability without erasing the profiles:

1. remove or revoke the `browser_hitl_private` Tool in Open WebUI;
2. run `docker compose stop`;
3. optionally restore `ENABLE_PLUGINS=false` and restart Open WebUI.

Do not remove the volume while there is intent to keep logins.

---

## 10. How to test in Open WebUI

1. Log in as admin or user-a.
2. Open a chat with a model that supports native tool calling.
3. In the `+`/Tools button, enable **Private browser with human login**.
4. Start with:

```text
Open https://example.com in my private browser and tell me the page title.
```

5. Then use a test account on a low-impact site:

```text
Open the login page of my test account. When you need credentials, stop and hand the browser to me.
```

6. The agent shows an explanatory Rich UI and a transient green panel in the corner of the page.
7. In the panel, click **Take over browser** on the Mac itself.
8. Perform the human step and click **Finish and hand back to the agent**.
9. Go back to the chat and say `continue`.
10. The agent should call `browser_status`, find `READY_TO_RESUME`, call `browser_resume` and continue.

Do not type password, MFA or CAPTCHA in the chat.

---

## 11. Validation evidence

The automated suite passed with **48 tests** (the Docker gate runs as the same non-root `cptr` user as the runtime), covering:

- IDOR between users;
- state machine and epochs;
- session reopening without overwriting the real tab URL;
- agent lock;
- token hash;
- twenty concurrent redemptions with exactly one winner;
- expiration of an unredeemed link to `READY_TO_RESUME`;
- an already-redeemed takeover completable even after the link initial deadline;
- fail-closed recovery;
- `READY_TO_RESUME` preserved if the runtime fails before the new lease;
- safe cleanup of stale Xvfb locks/sockets without removing an active display;
- unique slots;
- cookie and CSRF bound to the grant, including an `origin` policy compatible with the real Chromium POST;
- blocking of private destinations and non-web ports;
- policies against local schemes, QUIC and non-proxied WebRTC UDP, preserving the agent loopback CDP;
- `execute` panel restricted to the Tool, URL absent from the Rich UI/model context and safe encoding of the reason;
- explicit migration and uniqueness of the Access e-mail mapping;
- JWT signature, issuer, AUD, time, `type=app`, e-mail and `sub`;
- cross-owner blocking and path isolation on the public hostname;
- tokenless URL after redemption, cookie bound to the `sub` and noVNC headers in an allowlist;
- absolute intervention deadline, fail-closed reconciliation and revocation on identity change;
- rollback of an active takeover, one WebSocket per session and frame limits.

The Docker build runs the suite as a gate and also passed.

The real local test validated:

```text
navigate(example.com) → title "Example Domain"
request takeover      → WAITING_FOR_HUMAN
agent snapshot        → HTTP 423
real click on portal  → POST with origin-only Referer; HUMAN_ACTIVE
noVNC HTML proxy      → PASS
real noVNC browser    → automatic RFB authentication and connected state PASS
real click conclude   → READY_TO_RESUME
resume                → AGENT_ACTIVE with new epoch
```

Also validated:

- real recovery of two profiles after `SIGKILL`: one in `HUMAN_ACTIVE` and another in `WAITING_FOR_HUMAN`, both to `READY_TO_RESUME`, working runtime and new lease;
- two distinct profile folders in mode `0700` and runtime artifacts/logs in `0600`;
- VNC/websockify absent after handback;
- Chromium without `--no-sandbox`;
- a live attempt at `file:///etc/passwd` and `file:///run/secrets/tool-api-key` blocked by policy, with the agent CDP still working;
- live flags against QUIC and non-proxied WebRTC UDP;
- only `127.0.0.1:3210` published;
- key absent from `docker inspect`, logs and process snapshot;
- `ENABLE_VALVE_ENCRYPTION=true` effective; the Tool key was rotated and the Valve is in Fernet ciphertext;
- `execute` panel opened in the main context, human click without inherited sandbox and working portal/noVNC, without changing other iframes;
- old key and current key absent from `webui.db`, WAL and SHM after checkpoint/VACUUM;
- no existing encrypted backup contains the old key, since the Tool was created after the most recent backup;
- positive ACL for admin/user-a and negative for the others.

---

## 12. Mobile publication with Cloudflare Access

The portal was published at `https://browser.seudominio.com` on 26/08/2026, with a scope separate from the chat:

- `browser.seudominio.com`: Access application **Browser HITL - OTP**, One-Time PIN only, exact allowlist of admin and user-a and a one-hour session;
- `chat.seudominio.com`: remains without Cloudflare Access/OTP, protected only by the normal Open WebUI login; there is no Access application corresponding to this hostname;
- the route `chat.seudominio.com → http://127.0.0.1:3000` has no `originRequest.access`;
- the route `browser.seudominio.com → http://127.0.0.1:3210` requires the dedicated AUD both at the edge and in `cloudflared`.

The broker validates the JWT again at the origin: RS256 signature by the rotating JWKS, issuer `https://seudominio.cloudflareaccess.com`, exact AUD, `type=app`, `iat`, `nbf`, `exp`, `sub` and e-mail. The validated e-mail must match the immutable administrative mapping `Open WebUI UUID ↔ access_email` and the grant snapshot.

After redemption, the initial token is invalidated and leaves the URL completely. Portal, noVNC and WebSocket then use tokenless paths (`/portal`, `/viewer/vnc.html` and `/viewer/websockify`), with a `__Host-browser_hitl; Secure; HttpOnly; SameSite=Strict; Path=/` cookie also bound to the Access `sub`.

The human intervention has an absolute deadline equal to the lower of the JWT `exp` and 3600 seconds. On expiry, the broker closes the WebSocket/viewer, revokes the grant and moves the session to `READY_TO_RESUME`; it never returns control to the agent automatically. There is timer retry and reconciliation via `browser_status`.

The public hostname exposes only `/takeover/*`, `/portal`, `/portal/complete` and `/viewer/*`. `/tool/*`, `/admin/*`, `/health` and other paths return `404` on the public host, although they remain available on loopback. The viewer accepts only GET assets, one WebSocket per session, frames up to 16 MiB and strict header allowlists.

### Pending mobile test

The deployment and the re-audit gave **GO only for a first low-risk test**. It is still necessary to validate manually on the phone:

1. start a takeover on a disposable site or `example.com`;
2. confirm that the new tab opens `browser.seudominio.com`, not `127.0.0.1`;
3. enter the e-mail on the Cloudflare Access page;
4. receive and type the One-Time PIN **on the Access page, never in the chat**;
5. take over the noVNC, interact and conclude;
6. go back to the chat, run `browser_status`/`browser_resume` and confirm a new epoch;
7. repeat once with user-a to validate isolation between users.

Do not yet use primary Gmail, healthcare, bank, government or production administration. After the low-risk E2E, the following are still pending:

1. a separate encrypted backup policy for profiles, or an explicit decision not to back them up;
2. deprovisioning and definitive profile deletion;
3. LaunchAgent/autostart only after approval;
4. a simultaneous test with two people.

Residual risks:

- after login, the agent acts with the privileges of the authenticated account;
- e-mail/document content may contain prompt injection;
- Google, Meta or LinkedIn may detect and block automation;
- passkeys/Touch ID/USB keys may not work in the remote Linux viewer;
- the Mac/Open WebUI administrator remains technically able to access the profiles;
- the POC egress proxy does not replace a lower-layer network policy.

Irreversible or high-impact actions should require separate human confirmation: sending e-mail, publishing content, sharing files, changing permissions, deleting data, buying or changing account security.

---

## 13. References

- Open WebUI Tools: <https://docs.openwebui.com/features/extensibility/plugin/tools/development/>
- Open WebUI Rich UI: <https://docs.openwebui.com/features/extensibility/plugin/development/rich-ui/>
- Open WebUI reserved arguments: <https://docs.openwebui.com/features/extensibility/plugin/development/reserved-args/>
- OpenBrowser evaluated: <https://github.com/floomhq/openbrowser>
- Open WebUI Computer: <https://github.com/open-webui/computer>

---

## Conclusion

The POC proves locally the central requirement: **admin and user-a can have persistent and isolated profiles; the agent and the human share the same session/tab; and the broker prevents concurrent control or observation by the agent during human login**.

The next safe step is not to test the primary Google account immediately. The remote portal authentication has already been deployed with Cloudflare Access/OTP; what remains is to run the first mobile E2E with `example.com` and then a low-value account, validate the experience and the isolation of both users and only then consider more sensitive accounts.
