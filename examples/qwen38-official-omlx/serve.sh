#!/usr/bin/env bash
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

[[ -x "$VENV/bin/python" ]] || { echo "runtime ausente: $VENV/bin/python" >&2; exit 1; }
[[ -x /usr/bin/sandbox-exec ]] || { echo "sandbox-exec indisponível" >&2; exit 1; }
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

ACTIVE_CONTEXT="$($VENV/bin/python -c 'import json,sys; print(json.load(open(sys.argv[1]))["sampling"]["max_context_window"])' "$STATE/settings.json")"
printf 'profile : qwen38-official-omlx\n'
printf 'source  : Qwen/Qwen3.8-27B via fcmeyer oQ4e @ 0299356\n'
printf 'backend : oMLX 0.6.3rc1 / Lightning MTP depth <= 3\n'
printf 'context : %s total; output <= 8192\n' "$ACTIVE_CONTEXT"
printf 'network : outbound denied by macOS sandbox\n'
printf 'url     : http://127.0.0.1:8084/v1\n\n'

exec /usr/bin/sandbox-exec -f "$ROOT/sandbox.sb" "$VENV/bin/python" "$ROOT/secure_server.py"
