#!/usr/bin/env bash
# Builds the Piața Unirii SUMO networks (PLAN.md §6).
#   ./scripts/build_net.sh          -> sumo/net.net.xml (static program) + sumo/net_actuated.net.xml
#   ./scripts/build_net.sh --osm    -> additionally sumo/net_osm_raw.net.xml, the raw OSM import (reference only)
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh

COMMON=(
  --node-files sumo/src/piata_unirii.nod.xml
  --edge-files sumo/src/piata_unirii.edg.xml
  --type-files sumo/src/piata_unirii.typ.xml
  --no-turnarounds
  --crossings.guess
  --walkingareas
  --tls.yellow.time 3
  --tls.cycle.time 90
  --tls.left-green.time 6
  --junctions.corner-detail 5
  --offset.disable-normalization
)

netconvert "${COMMON[@]}" --tls.default-type static -o sumo/net.net.xml
python scripts/tune_tls.py sumo/net.net.xml
netconvert "${COMMON[@]}" --tls.default-type actuated -o sumo/net_actuated.net.xml
echo "OK: sumo/net.net.xml, sumo/net_actuated.net.xml"

if [[ "${1:-}" == "--osm" ]]; then
  netconvert --osm-files sumo/map.osm -o sumo/net_osm_raw.net.xml \
    --tls.guess-signals --tls.join --junctions.join --remove-edges.isolated \
    --keep-edges.by-vclass passenger --no-warnings
  echo "OK: sumo/net_osm_raw.net.xml (raw import, not used by the demo)"
fi
