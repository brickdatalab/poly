#!/bin/zsh
set -euo pipefail

WORKDIR="/Users/vitolo/Desktop/projects/polymarket-hub/v4"
LOGFILE="$WORKDIR/logs/open_interest_tick.log"

cd "$WORKDIR"
set -a
source .env
set +a

mkdir -p logs

if ! curl -fsS http://127.0.0.1:8787/health >/dev/null; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) health_check_failed" >> "$LOGFILE"
  exit 1
fi

curl -fsS -X POST http://127.0.0.1:8787/open-interest/tick \
  -H "X-API-Key: ${OPEN_INTEREST_API_KEY}" \
  >> "$LOGFILE" 2>&1

echo "" >> "$LOGFILE"
