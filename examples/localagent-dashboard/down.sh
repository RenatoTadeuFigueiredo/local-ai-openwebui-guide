#!/usr/bin/env bash
# Stop this profile's monitoring stack. Volumes survive, so history is kept.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PROFILE="$(cd "$ROOT/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT/.env"

PIDFILE="$PROFILE/state/monitoring/exporter-$EXPORTER_PORT.pid"

if [[ -f "$PIDFILE" ]]; then
  kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
fi

cd "$ROOT"
docker compose --env-file .env stop
