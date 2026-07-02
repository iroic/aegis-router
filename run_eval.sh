#!/bin/bash
PARAMS="--learn --learn-mode edge --nodes 20 --duration 3 --traffic-rate 6 --sybil-ratio 0.1 --drain 2 --state eval_state.json --seed 42"
start_time=$(date +%s.%N)
OUTPUT=$(python3 -m aegis_router.event_demo $PARAMS 2>&1)
exit_code=$?
runtime=$(bc <<< "$(date +%s.%N) - $start_time")
exit [ $exit_code -ne 0 ] && echo 'ERROR: Simulation failed' >&2 && exit 1
LEARNED_LINE=$(grep -A1 'learned #' <<< "$OUTPUT" | tail -1)
DELIVERY=$(grep -oP '(?<=delivery=)[0-9.]+' <<< "$LEARNED_LINE")
SYBIL=$(grep -oP '(?<=sybil=)[0-9.]+' <<< "$LEARNED_LINE")
echo "score: $(bc <<< "scale=3; $DELIVERY / 100")"
echo "metrics:"
echo "  delivery_ratio: $DELIVERY"
echo "  sybil_touch_ratio: $SYBIL"
echo "  runtime: $runtime"
