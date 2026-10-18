#!/usr/bin/env bash
# Starts the full demo on config server.port (3000): both SUMO simulations + dashboard (+ ESP32 when connected).
#   ./scripts/run_demo.sh               # real simulations, serial bridge on
#   ./scripts/run_demo.sh --no-serial   # without the board
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
(cd web && npm run build >/dev/null)
PORT=$(python -c "import yaml; print(yaml.safe_load(open('config.yaml'))['server']['port'])")
( sleep 4; open "http://localhost:$PORT" 2>/dev/null || true ) &
exec python -m server.main "$@"
