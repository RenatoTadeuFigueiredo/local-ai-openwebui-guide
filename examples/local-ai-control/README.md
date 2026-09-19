# Local AI stack on demand — `local-ai up`, `local-ai down`

> **English** · [Português](../../pt-br/examples/local-ai-control/README.md)

**Reference date:** September 19, 2026  
**Measured hardware:** MacBook Pro with Apple M3 Max, 40-core GPU and 128 GB of unified memory  
**System/runtime:** macOS 15 or later, `launchd` user domain

The deployed stack used to start at login: three LaunchAgents in `~/Library/LaunchAgents/` holding a
27B model, a 9B model, Open WebUI and a Tunnel. It worked, and it meant ~21 GB of unified memory plus
the WebUI and Tunnel processes were resident from login to logout, whether or not anyone was
chatting. This bundle keeps `launchd` as the supervisor but moves the trigger to a command:

```bash
local-ai up      # models, WebUI, then whatever else you asked for
local-ai down    # nothing left behind
```

---

## 1. Why it works

`launchd` loads exactly one user directory at login: `~/Library/LaunchAgents/`. A plist that lives
anywhere else is inert until someone bootstraps it. That is the whole trick — the plists move to
`~/.config/local-ai/agents/`, and `local-ai` calls `launchctl bootstrap` and `launchctl bootout`.

Nothing else changes. While a unit runs, `launchd` still owns it: `RunAtLoad`, `KeepAlive`,
`ThrottleInterval`, `WorkingDirectory` and stdout/stderr redirection all come from the plist, so a
crashing WebUI is still restarted and the logs still land where they always did. And `bootout` — not
`kill` — is the stop switch, which is what makes "off" stick: `KeepAlive` does not resurrect a job
that has been removed from the domain.

There is no daemon and no polling. `local-ai` is one bash script that reads health signals and exits.

---

## 2. Install

```bash
chmod +x local-ai
ln -sfn "$PWD/local-ai" ~/.local/bin/local-ai        # ~/.local/bin is on PATH; the repo copy stays live
mkdir -p ~/.config/local-ai/agents
for f in agents/*.plist.template; do
  sed "s|__HOME__|$HOME|g" "$f" > ~/.config/local-ai/agents/"$(basename "$f" .template)"
done
plutil -lint ~/.config/local-ai/agents/*.plist
```

If the stack was already running from the old login-time location, unload it once so the two
arrangements do not overlap:

```bash
for l in com.local.ornith-omlx com.local.qwen-omlx com.local.openwebui \
         com.local.cloudflared-openwebui com.local.docker-desktop-openwebui com.mlx-server; do
  launchctl bootout "gui/$(id -u)/$l" 2>/dev/null
done
```

`LOCAL_AI_AGENTS_DIR` overrides the plist directory if you keep them elsewhere.

---

## 3. Commands

```bash
local-ai up [--tunnel] [--docker] [--legacy] [--all] [--open]
local-ai down [--docker]
local-ai restart [flags]
local-ai status
local-ai logs <unit>
```

| Command | Effect |
|---|---|
| `up` | Ornith (`8086`), Qwen (`8084`), Open WebUI (`3000`) |
| `up --tunnel` | Adds the Cloudflare Tunnel — `chat.seudominio.com` answers again |
| `up --docker` | Adds Docker Desktop, needed by the optional terminal/Computer containers |
| `up --legacy` | Adds the old mlx-lm server on `8080` |
| `up --all` | The three optional units above, together |
| `up --open` | Opens the WebUI in the browser once it answers |
| `down` | Stops every managed unit that is running; leaves Docker Desktop alone |
| `down --docker` | Also quits Docker Desktop |
| `status` | Unit, `launchd` state, pid, port, health and resident memory |

`up` is idempotent (`already up`) and ordered: models first, then Open WebUI, then the Tunnel, each
one waited on through its own health signal. A unit that never becomes healthy is named, `up` exits
non-zero, and `local-ai logs <unit>` shows why.

`down` is idempotent too (`nothing was running`) and reports any process it could not stop instead of
claiming success.

---

## 4. The units

| Unit | Label | Port | Health signal |
|---|---|---|---|
| `ornith` | `com.local.ornith-omlx` | `8086` | `/health` + model present in `/api/status` |
| `qwen` | `com.local.qwen-omlx` | `8084` | same |
| `openwebui` | `com.local.openwebui` | `3000` | `/health` |
| `tunnel` | `com.local.cloudflared-openwebui` | `20241` | tunnel `/ready` |
| `docker` | `com.local.docker-desktop-openwebui` | — | `docker info` |
| `legacy` | `com.mlx-server` | `8080` | `/v1/models` |

The model units check that the *right* model is loaded, not just that a port answers: a profile that
came up with an empty engine pool is not reported as ready.

---

## 5. Measured

On the reference machine, after the switch:

| Operation | Result |
|---|---|
| `down` (5 units) | 3.6 s, ports `3000`, `8084`, `8086`, `20241`, `8080` released |
| `up` (cold, warm page cache) | 55 s total — 4 s Ornith, 5 s Qwen, 31 s Open WebUI, < 1 s Tunnel |
| `down --docker` | 18 s, Docker Desktop quit, its 8 containers stopped |
| Memory released by `down` | ~21 GB resident (Qwen 15.5 GB, Ornith 5.5 GB, WebUI 0.7 GB) plus the Docker VM |
| Chat through the public URL after a full `down`/`up` cycle | answered (`E2E-OK`) |

The Tunnel reconnects on the next `up --tunnel` with a new connector id; nothing is recreated in
Cloudflare.

---

## 6. Honest limits

- **Docker Desktop is shared.** A bare `down` leaves it running because other projects on this
  machine keep containers in it. Quitting it stops their containers too.
- **The model profiles have no `KeepAlive`.** A crash mid-session is not restarted — that was already
  true before this change. The WebUI and the Tunnel do have it.
- **A job loaded from the old path survives until it is booted out.** The unload loop in section 2
  handles it; after that, `local-ai status` should show `-` under `LAUNCHD` for everything.
- **A unit started by hand is stopped through its controller.** `down` falls back to
  `./ornith15-omlx stop` / `./qwen-omlx stop` when `launchd` never owned the process, and reports it
  if that also fails.
- **The plists keep absolute paths.** `__HOME__` is expanded at install time; the scripts they point
  at (`~/services/open-webui-mac/app/*.sh`) still have to exist.
- **`legacy` is the weakest unit.** Its readiness signal is only `/v1/models`; there is no verifier
  and no pinned checkpoint behind it, unlike the two oMLX profiles.
- **Nothing here survives a reboot by itself** — that is the point, but it means a Mac that reboots
  overnight needs one `local-ai up` before the phone can chat again.

---

## 7. Going back to autostart

Move the plists back into `~/Library/LaunchAgents/`. They carry `RunAtLoad` (and `KeepAlive` where it
matters), so they start at the next login exactly as before, and `local-ai` still works on top of
them because it only ever bootstraps and boots out by label.