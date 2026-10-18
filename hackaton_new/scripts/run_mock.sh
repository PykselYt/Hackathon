#!/usr/bin/env bash
# Dashboard on fake telemetry (no SUMO, fake ESP32): builds web/ if needed, serves on config server.port (3000).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
[[ -d web/dist ]] || (cd web && npm run build)
exec python -m server.main --mock "$@"
