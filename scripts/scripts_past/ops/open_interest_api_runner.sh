#!/bin/zsh
set -euo pipefail

WORKDIR="/Users/vitolo/Desktop/projects/polymarket-hub/v4"
PYTHON_BIN="/Users/vitolo/miniconda3/bin/python"

cd "$WORKDIR"
set -a
source .env
set +a

mkdir -p logs
exec "$PYTHON_BIN" scripts/run_open_interest.py --serve --host 127.0.0.1 --port 8787
