#!/usr/bin/env bash
set -euo pipefail

# ---------- CONFIGURATION ----------
WORKDIR="$(pwd)"
STATE_FILE="${WORKDIR}/aegis_state_grid.json"
RESULTS_TSV="${WORKDIR}/grid_results.tsv"

# Hyper‑parameters to test
EDGE_PENALTIES=(1.0 2.0 2.5 3.0)
RISK_BUDGETS=(0.20 0.22 0.25 0.30)

RUNS=15

# Header for results CSV
echo -e "edge_penalty\trisk_budget\tdelivery\tsybil\tdrop\tinflight" > "${RESULTS_TSV}"

# ---------- LOOP ----------
for EP in "${EDGE_PENALTIES[@]}"; do
  for RB in "${RISK_BUDGETS[@]}"; do
    rm -f "${STATE_FILE}"
    export EDGE_PENALTY="${EP}"
    export RISK_BUDGET="${RB}"
    echo "=== Test EP=${EP} RB=${RB} ==="
    python3 -m aegis_router.event_demo \
        --learn --learn-mode edge \
        --runs "${RUNS}" \
        --state "${STATE_FILE}" \
        --nodes 100 --duration 15 --traffic-rate 20 \
        --sybil-ratio 0.2 --drain 10 2>/dev/null | tee /tmp/run.out

    LAST_LINE=$(grep "^learned #" /tmp/run.out | tail -1)
    DELIVERY=$(echo "$LAST_LINE" | grep -oP 'delivery=\s*\K[0-9.]+')
    SYBIL=$(echo "$LAST_LINE" | grep -oP 'sybil=\s*\K[0-9.]+')
    DROP=$(echo "$LAST_LINE" | grep -oP 'drop=\s*\K[0-9.]+')
    INFLIGHT=$(echo "$LAST_LINE" | grep -oP 'inflight=\s*\K[0-9]+' || echo "0")
    echo -e "${EP}\t${RB}\t${DELIVERY}\t${SYBIL}\t${DROP}\t${INFLIGHT}" >> "${RESULTS_TSV}"
  done
done

# ---------- BEST ----------
echo -e "\n=== Raw results ==="
cat "${RESULTS_TSV}"

BEST=$(awk -F'\t' 'NR>1 && $4 <= 30 && $3 > best_delivery {best_delivery=$3; best_line=$0} END {print best_line}' "${RESULTS_TSV}")

echo -e "\n=== Best combo (max delivery, sybil ≤30%) ==="
echo -e "edge_penalty\trisk_budget\tdelivery\tsybil\tdrop\tinflight"
echo -e "${BEST}"
