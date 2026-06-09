#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# --- paramètres optimaux ---
EDGE=3.0          # pénalité forte sur les arêtes mauvaises
BUDGET=0.15       # budget de risque strict
RUNS=200
TRAFFIC=20        # paquets/s
DURATION=15
SYBIL=0.20
TTL=18
DRAIN=10

python3 -m aegis_router.event_demo \
  --learn --learn-mode edge \
  --runs "$RUNS" \
  --edge-penalty "$EDGE" \
  --risk-budget "$BUDGET" \
  --nodes 100 --duration "$DURATION" \
  --traffic-rate "$TRAFFIC" --sybil-ratio "$SYBIL" \
  --ttl "$TTL" --drain "$DRAIN" \
  > optimal_run.txt

# extraire les stats du dernier run (learned #$RUNS)
grep "^learned #" optimal_run.txt | tail -1 > final_stats.txt

echo "Run terminé — métriques finales dans final_stats.txt"
