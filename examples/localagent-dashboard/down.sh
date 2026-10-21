#!/usr/bin/env bash
# Stop the monitoring stack. Grafana and Prometheus keep their volumes, so the
# history survives the next `up.sh`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
STATE="$ROOT/../state"
PIDFILE="$STATE/monitoring/exporter.pid"

if [[ -f "$PIDFILE" ]]; then
  pid="$(cat "$PIDFILE")"
  kill "$pid" 2>/dev/null || true
  rm -f "$PIDFILE"
fi

cd "$ROOT"
docker compose stop
