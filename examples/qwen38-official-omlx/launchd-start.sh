#!/bin/zsh
# Start the profile as launchd's foreground child while preserving controller PID ownership.
set -euo pipefail
umask 077

SELF="${0:A}"
ROOT="${SELF:h}"
STATE="$ROOT/state"
PIDFILE="$STATE/server.pid"
PORT=8084

mkdir -p "$STATE"
if [[ -f "$PIDFILE" ]]; then
  old_pid="$(<"$PIDFILE")"
  if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
    command="$(ps -ww -o command= -p "$old_pid" 2>/dev/null || true)"
    if [[ "$command" == "$ROOT/runtime/venv/bin/python $ROOT/secure_server.py" ||
          "$command" == *"$ROOT/serve.sh"* ||
          "$command" == *"$ROOT/launchd-start.sh"* ]]; then
      echo "qwen38-official already runs as pid $old_pid; refusing a second supervisor" >&2
    else
      echo "PID file belongs to an unrelated live process: $old_pid" >&2
    fi
    exit 1
  fi
  rm -f "$PIDFILE"
fi

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port $PORT is already in use" >&2
  exit 1
fi

# serve.sh ultimately execs secure_server.py, preserving this PID. The regular
# controller can therefore inspect, stop, and restart a launchd-owned process.
# A normal/abnormal exit may leave a dead PID value; the next controlled start
# validates ownership/liveness and removes that stale file before reuse.
echo "$$" > "$PIDFILE"
exec "$ROOT/serve.sh"
