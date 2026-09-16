#!/usr/bin/env bash
# Isolated oMLX launcher for Ornith-1.5-9B oQ4e + Lightning MTP.
set -euo pipefail

SELF="${BASH_SOURCE[0]}"
while [[ -L "$SELF" ]]; do
  TARGET="$(readlink "$SELF")"
  [[ "$TARGET" == /* ]] && SELF="$TARGET" || SELF="$(dirname "$SELF")/$TARGET"
done
ROOT="$(cd "$(dirname "$SELF")" && pwd)"
STATE="$ROOT/state"
VENV="$ROOT/runtime/venv"
PRIVATE_HOME="$STATE/home"
PORT=8086
HOST="127.0.0.1"
SANDBOX="$ROOT/sandbox.sb"

[[ -x "$VENV/bin/python" ]] || { echo "private oMLX runtime missing: $VENV/bin/python" >&2; exit 1; }
[[ -r "$ROOT/secure_server.py" ]] || { echo "secure server entrypoint missing" >&2; exit 1; }
[[ -x /usr/bin/sandbox-exec ]] || { echo "macOS sandbox-exec is required" >&2; exit 1; }
[[ -r "$SANDBOX" ]] || { echo "network sandbox missing: $SANDBOX" >&2; exit 1; }
[[ -s "$STATE/api-key" ]] || { echo "API key missing: $STATE/api-key" >&2; exit 1; }
[[ -s "$STATE/secret-key" ]] || { echo "session secret missing: $STATE/secret-key" >&2; exit 1; }
"$VENV/bin/python" "$ROOT/verify-model.py" --quick >/dev/null

umask 077
mkdir -p "$STATE/cache" "$STATE/hf-cache" "$STATE/logs" "$PRIVATE_HOME"
export HOME="$PRIVATE_HOME"
export OMLX_BASE_PATH="$STATE"
export OMLX_SECURE_ENTRYPOINT=1
export HF_HOME="$STATE/hf-cache"
export HF_HUB_CACHE="$STATE/hf-cache/hub"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export OMLX_BONJOUR=0
export OMLX_NAX=0
export OMLX_QWEN35_QMM_NAX=0
export OMLX_QWEN35_ANE_PREFILL=0
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="$NO_PROXY"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

CTX_CAP="$("$VENV/bin/python" - "$STATE/settings.json" <<'PY'
import json
import sys
from pathlib import Path
settings = json.loads(Path(sys.argv[1]).read_text())
print(int(settings["sampling"]["max_context_window"]))
PY
)"
printf 'profile : ornith-omlx text-only\n'
printf 'backend : oMLX 0.6.3rc1 / Lightning MTP depth <= 3\n'
printf 'model   : Ornith-1.5-9B-oQ4e-mtp @ f601221\n'
printf 'ctx cap : %s total (output <= 8192)\n' "$CTX_CAP"
printf 'network : outbound denied by macOS sandbox\n'
printf 'url     : http://%s:%s\n\n' "$HOST" "$PORT"

# The private entrypoint exposes only health/status/model-list and completion
# routes. No admin, MCP, web, audio, download/upload, cluster, or mutation API is
# registered. The sandbox additionally fail-closes every outbound socket.
exec /usr/bin/sandbox-exec -f "$SANDBOX" "$VENV/bin/python" "$ROOT/secure_server.py"
