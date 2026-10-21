#!/usr/bin/env bash
# Bring the local monitoring stack up: exporter on the host, Prometheus and
# Grafana in Docker. Nothing starts at login; call this after `qwen-omlx start`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
STATE="$ROOT/../state"
VENV="$ROOT/../runtime/venv/bin/python"
PIDFILE="$STATE/monitoring/exporter.pid"
LOG="$STATE/monitoring/exporter.log"

mkdir -p "$STATE/monitoring"

if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "exporter already running (pid $(cat "$PIDFILE"))"
else
  nohup "$VENV" "$ROOT/exporter.py" >"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  echo "exporter started (pid $!) on http://127.0.0.1:8791/metrics"
fi

cd "$ROOT"
docker compose up -d

echo
echo "Grafana   : http://127.0.0.1:3300  (folder LocalAgent, admin/localagent)"
echo "Prometheus: http://127.0.0.1:9090"
