# Qwen3.8-27B derived from the official on M3 Max 128 GB

> **English** · [Português](../../pt-br/examples/qwen38-official-omlx/README.md)

**Reference date:** August 27, 2026  
**Reference/gate hardware:** MacBook Pro with Apple M3 Max, 40-core GPU and 128 GB of unified memory  
**System/runtime:** macOS 15 or later, Python 3.12, oMLX `0.6.3rc1`  
**Local model:** `qwen38-official-omlx`  
**API:** `http://127.0.0.1:8084/v1`

This is the recommended clean-room guide to install, without local quantisation, a community quantisation of the official `Qwen/Qwen3.8-27B` model:

```text
fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp
@ 02993567061709709fd60b38d64819e2b8f647a3
```

The `fcmeyer` checkpoint is public, Apache-2.0 and declares `Qwen/Qwen3.8-27B` as its base. It **is not a checkpoint published by the Qwen team**; it is a third-party quantised derivative. This bundle authenticates exactly the chosen revision and derived files, but does not prove tensor-to-tensor equivalence with the official BF16.

> The study in [`../docs/01-case-study-qwen38-m3-max.md`](../../docs/01-case-study-qwen38-m3-max.md) measured another checkpoint, `pyros-vault/Qwen3.8-27B-Uncensored-oQ4e-mtp`. The 46–50 tok/s results, the 256K canaries and the RSS recorded there are historical and **are not a performance promise for this profile**. This guide starts a fresh install, with another Model ID and another directory, without replacing the existing profile.

---

## 1. Expected result

When you finish, the machine will have:

- an oQ4e model already quantised, with approximately 17 GB of payload and native MTP preserved;
- oMLX and dependencies in an isolated Python 3.12 venv;
- Lightning MTP enabled with adaptive depth of up to 3 drafts;
- a total native context of `262144` tokens;
- output authoritatively capped at `8192` tokens and always subject to `prompt + output <= context`;
- concurrency of one request;
- persistent prefix cache capped at `40GB` on SSD;
- OpenAI-compatible API only on `127.0.0.1:8084`; five state/inference operations require Bearer and `GET /health` stays without Bearer for local liveness;
- a facade with six inference/state operations, with no admin panel, MCP, download, quantisation or model mutation;
- process in offline mode and with outbound network denied by `sandbox-exec`.

The profile forces the **text** engine (`llm`). Although the checkpoint includes the vision tower, this procedure does not expose multimodal input. It also does not apply YaRN nor extend to 1M: `262144` is the native limit used here.

### What is not included

- requantisation of the BF16;
- Open WebUI, OpenCode or Cloudflare installed automatically;
- benchmark or quality evaluation;
- backup of the weights/cache;
- full filesystem isolation.

The sandbox policy is `allow default` + `deny network-outbound`: it blocks egress, but the process still has the file accesses granted to the macOS user. The private `HOME` reduces accidental discovery; it is not a container nor a boundary against the user/root itself.

---

## 2. Pinned identities

| Component | Identity |
|---|---|
| Declared base | `Qwen/Qwen3.8-27B` |
| Executed checkpoint | `fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp` |
| Revision | `02993567061709709fd60b38d64819e2b8f647a3` |
| License declared on the Hub | Apache-2.0 |
| Indexed payload | `16971681484` bytes, about 15.81 GiB |
| Shards | 4 safetensors, all with pinned SHA-256 |
| MTP tensors | 29 |
| Wheel | `omlx-0.6.3rc1-cp312-cp312-macosx_15_0_universal2.whl` |
| Wheel SHA-256 | `7010ff68df48d38f17dde034fd6f3c2dd6c6c872bed29d42513506de4734362c` |
| MLX | `0.32.0` |
| mlx-lm | `0.31.3` |
| mlx-metal | `0.32.0` |

The verifier also pins the size and identity of the metadata, the `qwen3_5` architecture, native RoPE, the 262144 tokenizer, affine 4-bit/group 64 quantisation, a set of 2209 tensors and the critical oMLX sources installed. During installation it writes `SOURCE_MANIFEST.sha256`; every start verifies that the installer, the scripts, configurations and operational templates remain identical to the copy that passed the full gate. The installed `README.md` stays outside that gate so that it can receive operational notes without blocking the start.

**Supply chain limitation:** the wheel and the checkpoint are authenticated; Git dependencies are pinned to commits; the remaining PyPI wheels are pinned by version, but not yet by hash. The bundle is not a full `pip --require-hashes` lock of the whole `site-packages`. Install/pip and the pre-start verifier run before the sandbox and import dependencies; a compromised package can execute with the user's accesses. For a high-threat environment, generate and audit a wheelhouse by hashes, install with `--no-index --require-hashes` and reduce dependencies before using this path.

---

## 3. Capacity and disk

### Memory

This profile was sized specifically for **128 GB**. The advertised window is maximum capacity, not pre-allocated memory. The cost grows as the context actually filled increases.

For this hybrid architecture, a useful estimate of the full-attention KV is about:

| Filled context | Approximate attention KV |
|---:|---:|
| 32768 | 2 GiB |
| 65536 | 4 GiB |
| 131072 | 8 GiB |
| 262144 | 16 GiB |

Weights, recurrent state, MTP priming, prefill buffers and other processes come on top of that. The `safe` memory guard can reject/abort a request to preserve the system. Do not raise Metal/macOS limits to force a canary.

### Disk

The installer requires **70 GiB free on the target volume** for a fresh install:

- checkpoint + metadata: ~16 GiB;
- observed venv/runtime: ~1.1 GiB;
- configured SSD cache: up to `40GB` decimal, ~37.25 GiB;
- margin for download, logs and operation.

The cache grows on demand. It does not reserve 40 GB of RAM and does not make a 256K prefill instant. Do not include `state/cache/` nor the venv in a normal backup: they are rebuildable. Preserve configuration, owner-only secrets and the pinned identities.

---

## 4. Prerequisites

Use the normal user that will run MLX/Metal. Do not use `sudo` to install or serve the profile.

### 4.1 Check the machine

```bash
sw_vers
uname -m
system_profiler SPHardwareDataType SPDisplaysDataType
df -h "$HOME"
```

Expected:

```text
Chip: Apple M3 Max
Memory: 128 GB
Total Number of Cores (GPU): 40
Architecture: arm64
macOS: 15 or later
```

The installer runs this gate again and fails if the hardware is not exactly the target. `--skip-hardware-check` exists for controlled development, not for the recommended path.

### 4.2 Command Line Tools, Homebrew and Python 3.12

If needed:

```bash
xcode-select --install
```

Then:

```bash
brew install python@3.12
python3.12 --version
git --version
command -v python3.12
command -v git
```

The pinned wheel requires macOS 15+ and CPython 3.12. Do not use the global Python 3.13/3.14 for this runtime.

### 4.3 Port

```bash
lsof -nP -iTCP:8084 -sTCP:LISTEN
```

The output must be empty. If another profile already uses `8084`, stop it deliberately or choose a migration with downtime. Do not change only one occurrence of the port: the bundle pins it in the launcher, configuration, facade and verifier.

---

## 5. Clean-room install

Run from the root of a **trusted/versioned copy of this workspace**:

```bash
cd examples/qwen38-official-omlx
./install.sh --target "$HOME/models/qwen38-official-omlx"
```

This local directory is not yet published as an external release/commit in this guide; therefore, the first acquisition of the bundle is not reproducible from the URLs below alone. When sharing it, distribute a signed archive or an immutable commit/tag URL with SHA-256 and record that value next to the guide. `SOURCE_MANIFEST.sha256` protects the copy **after** installation, but does not authenticate the initial origin.

The flow:

1. validates hardware, macOS, tools and space;
2. downloads the wheel from the GitHub release and verifies SHA-256;
3. creates the Python 3.12 venv and installs pinned versions;
4. downloads the immutable checkpoint revision (~17 GB) directly into `model/`;
5. generates random API key and session secret in `state/`, mode `0600`;
6. materialises a coherent 256K configuration;
7. runs the full cryptographic verification, including the four shards;
8. creates the optional `~/bin/qwen38-official` symlink.

The model repository is public and does not require a Hugging Face token. Do not use `--skip-download` in a normal install; it exists only for restore/tests whose content will be authenticated by the verifier.

### 5.1 Expected result

```text
Install validated.
Profile: .../models/qwen38-official-omlx
Model:   qwen38-official-omlx
API:     http://127.0.0.1:8084/v1
```

The full verification re-reads and hashes ~17 GB; it can take several minutes.

### 5.2 Optional PATH

The symlink already goes into `~/bin`. If that directory is not in PATH, add it once:

```bash
grep -F 'export PATH="$HOME/bin:$PATH"' "$HOME/.zshrc" >/dev/null 2>&1 || \
  printf '\nexport PATH="$HOME/bin:$PATH"\n' >> "$HOME/.zshrc"
source "$HOME/.zshrc"
command -v qwen38-official
```

Without changing the shell, use the absolute path:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
"$PROFILE/qwen38-official" status
```

---

## 6. Verification before the first start

```bash
PROFILE="$HOME/models/qwen38-official-omlx"

cat "$PROFILE/.qwen38-official-profile"
cat "$PROFILE/MODEL_REVISION"
"$PROFILE/runtime/venv/bin/python" -m pip check
"$PROFILE/qwen38-official" verify
```

The first two outputs must contain the pinned revision. The last command is the full cryptographic verification.

For the quick structural gate used on every start:

```bash
"$PROFILE/qwen38-official" verify --quick
```

`--quick` validates versions, structure, sizes, configuration, isolation, routes and guard regressions, but does not recompute every hash of the 17 GB. Use the full verification after install, restore, copy or suspected corruption.

---

## 7. First start and smoke test

### 7.1 Start

```bash
qwen38-official start
qwen38-official status
```

The first command waits until the model is loaded. Do not read `/health` alone as ready; the controller requires `qwen38-official-omlx` in `loaded_models`.

### 7.2 Check the bind and the advertised model

```bash
PROFILE="$HOME/models/qwen38-official-omlx"

lsof -nP -iTCP:8084 -sTCP:LISTEN
curl --fail --silent --show-error \
  -H @"$PROFILE/state/auth-header" \
  http://127.0.0.1:8084/v1/models \
  | python3 -m json.tool

curl --fail --silent --show-error \
  -H @"$PROFILE/state/auth-header" \
  http://127.0.0.1:8084/v1/models/status \
  | python3 -m json.tool
```

Require:

- a listener exclusively on `127.0.0.1:8084`;
- Model ID `qwen38-official-omlx`;
- `max_model_len: 262144`;
- `model_context_length: 262144`;
- `max_context_window: 262144`;
- `max_tokens: 8192`;
- text engine/model type.

Fail if there is `0.0.0.0:8084`, `*:8084` or `[::]:8084`.

### 7.3 Functional smoke

```bash
qwen38-official chat "Responda somente com a palavra OK."
```

Then confirm Lightning MTP in the log:

```bash
grep -E 'Speculative backend selected.*Lightning MTP|MTP path activated|MTP\[' \
  "$PROFILE/state/logs/server.log" | tail -10
```

Require a `Lightning MTP (model_type=qwen3_5, active)` selection and fresh request evidence (`MTP path activated` + `MTP[...]` summary). The `mtp_enabled=true` setting alone does not prove the path was used.

### 7.4 Negative authentication

```bash
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  -H 'Content-Type: application/json' \
  http://127.0.0.1:8084/v1/chat/completions \
  --data '{
    "model":"qwen38-official-omlx",
    "messages":[{"role":"user","content":"teste"}],
    "max_tokens":1
  }'
```

Expected: `401` or `403`.

---

## 8. Validate context without confusing metadata with capacity

There are four different levels:

1. **structural integrity:** checkpoint and tokenizer declare `262144`;
2. **runtime:** endpoints advertise `262144`;
3. **real inference above 32K:** a prompt >32768 is processed and produces output;
4. **exact boundary:** `prompt + output = 262144` with no internal overshoot.

The installer proves 1 and the first start proves 2. Run 3 before promoting 256K to clients. Level 4 is expensive and optional; do not treat it as an everyday test.

### 8.1 Recommended initial canary: 40K

The script uses the local tokenizer, builds exactly the requested number of tokens, performs an authenticated raw completion, requires coherent counts/finish and real MTP use in the log. Run it with no other concurrent requests so that the fresh MTP evidence belongs unambiguously to the canary:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
"$PROFILE/runtime/venv/bin/python" "$PROFILE/context-canary.py" \
  --prompt-tokens 40000 \
  --max-tokens 4 \
  --require-mtp \
  | tee "$PROFILE/state/context-canary-40k.json"
```

Monitor in another terminal:

```bash
qwen38-official status
memory_pressure
```

This test can take several minutes. Require:

- `server_prompt_tokens: 40000`;
- `completion_tokens` between 1 and 4;
- a total of at most 40004;
- `fresh_mtp_log_evidence: true`;
- a healthy service at the end;
- no `prefill_memory_aborted` or `_MtpSafetyViolation`.

It proves capacity above 32K on the new checkpoint; it does not prove long-recall quality nor a full 256K.

### 8.2 Optional ladder

Only if 40K passes and there is a real need:

```bash
for TOKENS in 65536 131072 245760; do
  "$PROFILE/runtime/venv/bin/python" "$PROFILE/context-canary.py" \
    --prompt-tokens "$TOKENS" --max-tokens 1 \
    | tee "$PROFILE/state/context-canary-$TOKENS.json" || break
done
```

Stop at the first error, memory guard, severe pressure or unacceptable latency. With concurrency 1, each prefill monopolises the model. A ~245K canary can take tens of minutes and must be run on mains power, with concurrent workloads closed.

### 8.3 Optional exact boundary

```bash
"$PROFILE/runtime/venv/bin/python" "$PROFILE/context-canary.py" \
  --prompt-tokens 262143 --max-tokens 1 \
  | tee "$PROFILE/state/context-canary-boundary.json"
```

This test requires exactly `262143 + 1 = 262144`. At the final position the guard may reduce MTP to ordinary decode; that is why the boundary does not use `--require-mtp`. Do not run it as a simple smoke. A success proves admission/positioning in that state; it does not measure a cold prefill if there is cache, nor semantic quality. The mandatory MTP evidence already belongs to the 40K canary, where there is room for speculation.

---

## 9. Daily operation

```bash
qwen38-official start
qwen38-official status
qwen38-official chat "seu prompt"
qwen38-official restart
qwen38-official stop
```

Continuous logs:

```bash
qwen38-official logs
qwen38-official launcher-logs
```

Use `Ctrl-C` to leave the `tail`; this does not stop the server.

### Metrics

`qwen38-official status` shows:

- active/queued requests;
- generation average reported by the process since the start;
- memory used/model ceiling.

The `chat` command also prints the `usage` object returned by the request. A global average is not equivalent to the speed of a specific response; prompt, length, MTP acceptance, filled context and temperature change the result.

---

## 10. OpenCode

This section was verified with OpenCode `1.18.23`. It assumes the CLI was already installed by the official method chosen by the user; since install channels change, see <https://opencode.ai/docs/>. Before configuring:

```bash
command -v opencode
opencode --version
```

If the version differs, validate the JSON against `https://opencode.ai/config.json` and review the migration notes. The integration uses the local OpenAI-compatible endpoint. The example below avoids writing the literal API key into the JSON: OpenCode expands `{file:...}` officially.

Back up the existing configuration before merging the block:

```bash
mkdir -p "$HOME/.config/opencode"
cp -p "$HOME/.config/opencode/opencode.json" \
  "$HOME/.config/opencode/opencode.json.backup-$(date +%Y%m%d-%H%M%S)" \
  2>/dev/null || true
```

In `~/.config/opencode/opencode.json` or in a project `opencode.json`, **merge**:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "qwen38-official": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Qwen3.8 27B derivado do oficial — oMLX local",
      "options": {
        "baseURL": "http://127.0.0.1:8084/v1",
        "apiKey": "{file:~/models/qwen38-official-omlx/state/api-key}",
        "timeout": 7200000,
        "chunkTimeout": 600000
      },
      "models": {
        "qwen38-official-omlx": {
          "name": "Qwen3.8 27B oQ4e + Lightning MTP",
          "limit": {
            "context": 262144,
            "output": 8192
          }
        }
      }
    }
  },
  "model": "qwen38-official/qwen38-official-omlx",
  "small_model": "qwen38-official/qwen38-official-omlx",
  "compaction": {
    "auto": true,
    "prune": true,
    "reserved": 16384
  },
  "permission": {
    "edit": "ask",
    "bash": {
      "*": "ask",
      "rm -rf *": "deny",
      "git reset --hard*": "deny",
      "git clean -fd*": "deny"
    },
    "task": "ask",
    "external_directory": "ask",
    "webfetch": "ask",
    "websearch": "ask"
  },
  "share": "disabled"
}
```

Why `reserved: 16384`: up to 8192 tokens can be used by the output; the rest is nominal margin for compaction/tool schemas. It is not a hard reservation on the server. The facade remains the final authority and reduces/rejects when the rendered prompt leaves no room.

Validate the syntax, discovery and inference without printing the resolved configuration — it can contain the expanded contents of the key file:

```bash
python3 -m json.tool "$HOME/.config/opencode/opencode.json" >/dev/null
opencode models qwen38-official --verbose
opencode run --model qwen38-official/qwen38-official-omlx \
  "Responda somente: OK"
```

In the TUI, use `/models` to select the model. The policy above denies some destructive patterns and requires approval for editing, shell, subagents, external directories and network. `write` is handled by the `edit` control in the current schema. Project/managed configurations can change or override the global one; review the repository's `opencode.json` and the precedence before trusting the gate. Do not use `--auto` just because inference is local.

### Tokens and speed in OpenCode

```bash
opencode stats --models
opencode stats --days 1 --models
```

`stats` shows persisted aggregate usage. In version `1.18.23`, there is no official panel that combines, for the current session, full consumption and server tokens/s. For per-request speed, check the `usage` in the oMLX API/logs; `qwen38-official status` shows a process average, not an isolated OpenCode session.

---

## 11. Open WebUI

For a fresh install, choose the hosting, but treat this README as the authority for the **model**:

- everything on the Mac: use [`../docs/02-deploy-macos-cloudflare-tunnel.md`](../../docs/02-deploy-macos-cloudflare-tunnel.md) only to install/configure Open WebUI, security, Tunnel and backup. **Replace entirely** the `qwen-omlx`/`qwen38-omlx` sections, the 256K integration, autostart and model rollback with sections 5–13 of this README; do not run the historical commands/paths of the uncensored profile;
- WebUI on a VPS: [`../docs/03-deploy-with-vps.md`](../../docs/03-deploy-with-vps.md) already adopts `qwen38-official-omlx` for the local provider.

In the Admin Panel:

```text
Admin Settings → Connections → OpenAI → Add Connection
```

When Open WebUI runs **on the same Mac**:

```text
URL:       http://127.0.0.1:8084/v1
API Key:   contents of ~/models/qwen38-official-omlx/state/api-key
Prefix ID: local
Model IDs (Filter): qwen38-official-omlx
Resulting ID in Open WebUI: local.qwen38-official-omlx
```

If Open WebUI is in **Docker on the same Mac**, `127.0.0.1` points at the container, not at the host; use a deliberate origin such as `host.docker.internal` and preserve firewall/auth, or prefer the runbook's native install. If it is on the VPS, the URL will be the hostname protected by the runbook's Tunnel/Access; keep Bearer and Service Auth separate.

The connection Model ID is `local.qwen38-official-omlx`. If you create a workspace model/alias, use **the same ID** `local.qwen38-official-omlx` and grant `read` only to the desired public/groups; then validate with a regular account both the base model returned by the connection and the workspace model. If the Open WebUI version prevents an alias with the same ID, use another explicit ID and update `CONTEXT_COMPACTION_MODEL` to it — do not let the two names diverge silently. Do not configure the key in the browser and keep **Direct Connections** off.

### 256K compaction

Recommended configuration:

```dotenv
ENABLE_CONTEXT_COMPACTION=true
CONTEXT_COMPACTION_MODEL='local.qwen38-official-omlx'
CONTEXT_COMPACTION_TOKEN_THRESHOLD=245760
CONTEXT_COMPACTION_TOKEN_CAP=245760
CONTEXT_COMPACTION_RETENTION_PERCENTAGE=40
```

Persist the same values in the Admin Panel and in the workspace model, because saved ConfigVars can prevail over the environment file.

`245760` leaves a nominal gap of 16384 up to `262144`; up to 8192 can be used by output and the rest absorbs system prompt, Tools and estimation error when it fits. Tools can be injected after the estimate. Therefore:

- compaction does not guarantee that every request will be accepted;
- the output can be reduced;
- the facade can reject if the final prompt consumes the window;
- never configure Open WebUI as if the model accepted `262144` of **input plus** `8192` of output.

Before offering the model to other users, validate through the WebUI proxy: discovery, streaming, ACL, compaction and a prompt above 32K on the new checkpoint.

---

## 12. Optional autostart with LaunchAgent

First finish installation, verification and the manual smoke. Then stop the controller:

```bash
qwen38-official stop
```

Generate the plist with `plistlib` — including if the target has characters that require XML escaping — without editing placeholders manually:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
PLIST="$HOME/Library/LaunchAgents/com.local.qwen38-official.plist"
mkdir -p "$HOME/Library/LaunchAgents"

python3 - "$PROFILE" "$PLIST" <<'PY'
import pathlib,plistlib,sys
root=pathlib.Path(sys.argv[1]).resolve()
out=pathlib.Path(sys.argv[2])
plist={
    "Label":"com.local.qwen38-official",
    "ProgramArguments":[str(root/"launchd-start.sh")],
    "RunAtLoad":True,
    "ThrottleInterval":30,
    "ProcessType":"Interactive",
    "WorkingDirectory":str(root),
    "StandardOutPath":str(root/"state/launchd.out.log"),
    "StandardErrorPath":str(root/"state/launchd.err.log"),
}
with out.open("wb") as target:
    plistlib.dump(plist,target,fmt=plistlib.FMT_XML,sort_keys=False)
out.chmod(0o600)
PY

plutil -lint "$PLIST"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
```

The LaunchAgent starts after user login, not before. Wait and validate:

```bash
launchctl print "gui/$(id -u)/com.local.qwen38-official"
qwen38-official status
```

With the LaunchAgent installed:

- `qwen38-official status`, `logs`, `chat` and `verify` remain valid;
- `qwen38-official restart` uses `launchctl kickstart`;
- `start`/`stop` refuse parallel lifecycle to avoid two supervisors;
- the template does not use `KeepAlive`: a crash does not restart automatically. This avoids a restart loop of the heavy model; monitor the job and do a deliberate `kickstart` if you want recovery.

This bundle keeps the classic `~/Library/LaunchAgents/` placement, which starts the profile at login.
To keep it off until asked, put the plist in `~/.config/local-ai/agents/` instead and drive it with
[`../local-ai-control/`](../local-ai-control/).

Stop and remove the autostart, without deleting the model:

```bash
launchctl bootout "gui/$(id -u)/com.local.qwen38-official"
rm "$HOME/Library/LaunchAgents/com.local.qwen38-official.plist"
```

This is not destructive for the profile. After removing the plist, `qwen38-official start` is the manual authority again.

---

## 13. Rollback to 32K

Use rollback if 256K produces pressure, latency or monopolisation incompatible with real use. Define once in this section:

```bash
PROFILE="$HOME/models/qwen38-official-omlx"
```

### Manual

```bash
qwen38-official stop
qwen38-official context 32768
qwen38-official start
```

If launchd is installed:

```bash
launchctl bootout "gui/$(id -u)/com.local.qwen38-official"
qwen38-official context 32768
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.local.qwen38-official.plist"
```

Do not leave the job merely loaded/idle during the change: `context` requires a free port **and** an unloaded label to prevent a concurrent restart.

`context` changes both JSONs transactionally and only completes if the quick verifier passes. The checkpoint/tokenizer stay native at 262144; only the operational ceiling becomes 32768.

Then require:

```bash
curl --fail --silent --show-error \
  -H @"$PROFILE/state/auth-header" \
  http://127.0.0.1:8084/v1/models | python3 -m json.tool
```

`max_model_len` must be `32768`. Also run:

```bash
qwen38-official chat "Responda somente: OK"
```

Adjust the clients before reopening normal use:

- OpenCode: in `qwen38-official-omlx.limit`, `context: 32768`; in `compaction`, `reserved: 8192` or more. Validate with `opencode models qwen38-official --verbose` and a short `opencode run`;
- Open WebUI: global and persisted threshold/cap to `24000`; workspace model `local.qwen38-official-omlx` with context `32768`. Restart and validate `/v1/models` through the proxy, compaction and chat with a regular account.

Going back to native requires restoring **server and clients**:

```bash
qwen38-official stop
qwen38-official context 262144
qwen38-official start
qwen38-official chat "Responda somente: OK"
```

Then restore OpenCode to `context: 262144`/`reserved: 16384`; restore Open WebUI and the workspace model to threshold/cap `245760` and context `262144`; restart and repeat the discovery, compaction, ACL and chat gates. In 262144 mode, the script guarantees the SSD cache configured at `40GB`. Do not delete `state/cache/` with `rm -rf` during rollback; let the manager apply its ceiling.

---

## 14. Update and restore

Do not silently swap branch, revision, wheel or dependencies. This bundle is a frozen profile. Before re-running `install.sh` over a valid profile, obtain a trusted copy of the corresponding bundle: the manifest detects drift relative to the installed copy, but does not replace an external signature of the origin; wheel/checkpoint and critical oMLX sources have the additional gates described above.

Before updating:

1. stop/unload the LaunchAgent;
2. preserve configuration and owner-only secrets;
3. create another profile directory;
4. review release notes and recompute/pin identities;
5. install and test on a separate port or in a maintenance window;
6. promote only after smoke, MTP, context and clients pass.

### What to keep

Keep encrypted:

- `.qwen38-official-profile`, `MODEL_REVISION` and `SOURCE_MANIFEST.sha256`;
- scripts/templates of this bundle, including `install.sh`;
- `state/settings.json` and `state/model_settings.json`;
- `state/api-key`, `state/secret-key` and `state/auth-header`;
- results of the canaries you ran;
- the final plist, if any.

The weights can be downloaded again from the revision and authenticated by the hashes. Venv and cache are also rebuildable. If the requirement is recovery without Internet/Hub, keep an encrypted copy of the four shards and the wheel in independent storage and validate `qwen38-official verify` after restoring.

By default, the installer refuses any target that already exists: install/update in another directory, validate and promote deliberately. An in-place repair of the same revision requires explicit authorisation `QWEN38_ALLOW_IN_PLACE_REPAIR=1`, an exact marker and a stopped profile/LaunchAgent; it still is not transactional and can leave downtime if pip/network fails. Arbitrary directories or a marker from another revision are always refused.

---

## 15. Safe removal

Removing the profile deletes weights, venv, cache and keys. This is destructive; back up what you need and confirm the path first.

1. unload the LaunchAgent or stop manually;
2. remove the `~/bin/qwen38-official` symlink if it points at this profile;
3. archive/rotate the keys used by OpenCode/Open WebUI;
4. remove the client connections;
5. only then delete `~/models/qwen38-official-omlx` deliberately.

This guide does not provide an automatic removal command, to avoid deleting the wrong target.

---

## 16. Acceptance checklist

### Installation

- [ ] hardware is M3 Max / 40 GPU / 128 GB;
- [ ] macOS is 15+ and Python is 3.12;
- [ ] there are at least 70 GiB free on the target volume;
- [ ] checkpoint revision is `02993567061709709fd60b38d64819e2b8f647a3`;
- [ ] wheel SHA-256 matches;
- [ ] `pip check` passes;
- [ ] full cryptographic verification passes;
- [ ] no secret was placed in Git, shell history or screenshot.

### Service

- [ ] listener is `127.0.0.1:8084` only;
- [ ] a request without Bearer is denied;
- [ ] `/v1/models` advertises `qwen38-official-omlx` and the expected context;
- [ ] smoke returns content;
- [ ] the log proves Lightning MTP active on the request;
- [ ] the process has no egress;
- [ ] only the six facade routes are exposed;
- [ ] there is no other profile on port 8084.

### Context

- [ ] 40K canary passed on the new checkpoint;
- [ ] memory/TTFT were observed and accepted;
- [ ] the deep ladder was run only if necessary;
- [ ] OpenCode/Open WebUI use `prompt + output`, not 262K + 8K;
- [ ] clients have compaction/margin configured;
- [ ] the 32768 rollback was rehearsed before depending on 256K in production.

### Clients

- [ ] OpenCode uses `{file:...}`, not a literal key;
- [ ] OpenCode resolves context 262144 and output 8192;
- [ ] Open WebUI uses a server-to-server connection, without Direct Connections;
- [ ] workspace model/ACL use `local.qwen38-official-omlx`;
- [ ] streaming and compaction were tested through the real path;
- [ ] any Tunnel preserves loopback and double authentication as per the runbook.

---

## 17. References

- Official Qwen: <https://huggingface.co/Qwen/Qwen3.8-27B>
- Pinned derived checkpoint: <https://huggingface.co/fcmeyer/Qwen3.8-27B-MLX-oQ4e-mtp/tree/02993567061709709fd60b38d64819e2b8f647a3>
- oMLX `v0.6.3rc1`: <https://github.com/jundot/omlx/releases/tag/v0.6.3rc1>
- OpenCode — providers: <https://opencode.ai/docs/providers/>
- OpenCode — config and `{file:...}`: <https://opencode.ai/docs/config/>
- Open WebUI — OpenAI-compatible provider: <https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/>

---

## 18. Conclusion

For a machine equal to the reference hardware, the simplest and most auditable path is to **download the oQ4e+MTP ready-made**, not to download ~56 GB of BF16 and requantise locally. The bundle/guards were structurally validated in that compatible environment, but the `fcmeyer` checkpoint still requires the first empirical smoke and canary on the destination install. The profile keeps the native 262144 window, applies fail-closed limits and keeps the API on loopback.

The recommendation remains conditional on three distinct gates:

1. bundle/checkpoint integrity;
2. real inference and MTP on this checkpoint;
3. quality and context representative of the installer's own use.

Passing the first gate does not imply the other two. In particular, the historical results of the uncensored model must not be attributed to this official derivative without a new controlled measurement.
