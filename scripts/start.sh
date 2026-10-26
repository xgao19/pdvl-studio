#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
python -m pdvl.cli init
if [[ "${PDVL_CODEX_ENABLED:-0}" == "1" ]]; then
  python -m pdvl.cli worker &
  WORKER_PID=$!
  trap 'kill "$WORKER_PID" 2>/dev/null || true' EXIT INT TERM
fi
python -m pdvl.cli serve
