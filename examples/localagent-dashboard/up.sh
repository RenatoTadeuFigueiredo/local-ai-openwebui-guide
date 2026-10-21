#!/usr/bin/env bash
# Bring this profile's monitoring stack up: exporter on the host, Prometheus and
# Grafana in Docker. Nothing starts at login; call this after `qwen-omlx start`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PROFILE="$(cd "$ROOT/.." && pwd)"
STATE="$PROFILE/state"
LOG_DIR="$STATE/monitoring"

# shellcheck disable=SC1091
source "$ROOT/.env"

PIDFILE="$LOG_DIR/exporter-$EXPORTER_PORT.pid"
LOG="$LOG_DIR/exporter.log"

mkdir -p "$LOG_DIR"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "exporter already running (pid $(cat "$PIDFILE"))"
else
  PROFILE_ROOT="$PROFILE" \
  FACADE_URL="$FACADE_URL" \
  API_KEY_FILE="$STATE/api-key" \
  LOG_FILE="$STATE/launcher.log" \
  EXPORTER_PORT="$EXPORTER_PORT" \
    nohup "$PROFILE/runtime/venv/bin/python" "$ROOT/exporter.py" >"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  echo "exporter started (pid $!) on http://127.0.0.1:$EXPORTER_PORT/metrics"
fi

cd "$ROOT"
docker compose --env-file .env up -d

echo
echo "Grafana   : http://127.0.0.1:$GRAFANA_PORT  (folder LocalAgent, admin)"
echo "Prometheus: http://127.0.0.1:$PROM_PORT"
