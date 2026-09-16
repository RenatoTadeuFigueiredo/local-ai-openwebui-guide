# browser-hitl-poc — reference implementation

> **English** · [Português](../../pt-br/examples/browser-hitl-poc/README.md)

Multi-user browser broker with persistent Chromium profiles, per-user isolation and
**fenced human takeover**: the agent and the person share the same session/tab, and the broker blocks
concurrent control or observation during the human login.

This directory is the **reference implementation** of what the document
[`../../docs/04-browser-hitl-multi-user-poc.md`](../../docs/04-browser-hitl-multi-user-poc.md)
describes. Read the document first; the code here exists for those who want to see how the
behaviour was built.

> **It is not a project to clone and run straight away.** It reflects a concrete deployment. To
> reproduce it, generate your own secrets, choose your own domain and adjust the configuration.

---

## What is here

| File | Role |
|---|---|
| `browser_hitl/runtime.py` | Chromium lifecycle, persistent profiles, flags and policy |
| `browser_hitl/api.py` | HTTP endpoints, takeover handshake, server-side lock |
| `browser_hitl/security.py` | Cloudflare Access identity validation, TTL and epoch |
| `browser_hitl/store.py` | State, ownership by UUID and auditing |
| `browser_hitl/egress_proxy.py` | Egress proxy with allowlist |
| `browser_hitl/settings.py` | Configuration from environment variables |
| `openwebui/browser_hitl_tool.py` | Open WebUI native tool |
| `tests/` | 8 files, 789 lines, covering lock, isolation, hardening and takeover |
| `chromium-seccomp.json` | seccomp profile (`defaultAction: SCMP_ACT_ERRNO`) |
| `chromium-policy.json` | Browser policy |
| `compose.yaml` | Container execution, with `cap_drop: ALL` and `no-new-privileges` |

## Run

```bash
cd examples/browser-hitl-poc

# 1. configuration — the templates are versioned, the real ones are not
cp .env.example .env
for k in tool-api-key admin-api-key portal-signing-key; do
  cp "secrets/$k.example" "secrets/$k"
  python3 -c "import secrets;print(secrets.token_urlsafe(48),end='')" > "secrets/$k"
  chmod 600 "secrets/$k"
done

# 2. tests
python3 -m venv .test-venv
. .test-venv/bin/activate
pip install -e '.[test]'
pytest -q

# 3. bring it up (Docker)
docker compose up --build
```

The service listens on `127.0.0.1:3210`. The container runs as a non-root user `cptr`, with
`HOME=/home/cptr` — that is the user *inside the container*, not yours.

## Configuration

All keys come from environment variables, with the `BROWSER_HITL_` prefix. The ones that matter:

| Variable | What it is for |
|---|---|
| `BROWSER_HITL_PUBLIC_BASE_URL` | Public URL of the portal |
| `BROWSER_HITL_ACCESS_REQUIRED` | Requires Cloudflare Access identity |
| `BROWSER_HITL_ACCESS_TEAM_DOMAIN` | Access team domain (`https://<team>.cloudflareaccess.com`) |
| `BROWSER_HITL_ACCESS_AUDIENCE` | AUD of the Access application — **replace it with yours** |
| `BROWSER_HITL_HUMAN_CONTROL_TTL_SECONDS` | Absolute deadline for the human takeover |
| `BROWSER_HITL_*_SECRET_FILE` | Path of the three secrets mounted at `/run/secrets/` |

## Security

The design assumes the portal is **published** and treats identity as untrusted:

- secrets in `0600` files, mounted `read_only`, never in a host environment variable
- `cap_drop: ALL`, `no-new-privileges`, seccomp with deny by default
- server-side lock (`423`) between agent and human, with epoch for resumption
- validation of the Access JWT before any privileged operation

The secrets versioned here are the **real ones of the deployment** — publishing them is intentional, and
Access still requires a One-Time PIN. If you run your own, generate your own.

---

Document describing this POC: [`../../docs/04-browser-hitl-multi-user-poc.md`](../../docs/04-browser-hitl-multi-user-poc.md)