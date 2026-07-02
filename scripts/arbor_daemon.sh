#!/usr/bin/env bash
set -u

ROOT="${AEGIS_ARBOR_ROOT:-/home/ghost/projects/aegis-router}"
CODEX_BIN="${CODEX_BIN:-/home/ghost/.npm-global/bin/codex}"
STATE_DIR="$ROOT/.arbor/daemon"
PROMPT_FILE="$ROOT/scripts/arbor_daemon_prompt.md"
INTERVAL_SECONDS="${AEGIS_ARBOR_INTERVAL_SECONDS:-300}"
ERROR_BACKOFF_SECONDS="${AEGIS_ARBOR_ERROR_BACKOFF_SECONDS:-1800}"
MAX_CYCLE_SECONDS="${AEGIS_ARBOR_MAX_CYCLE_SECONDS:-14400}"

mkdir -p "$STATE_DIR"

exec 9>"$STATE_DIR/daemon.lock"
if ! flock -n 9; then
  echo "Another Aegis Arbor daemon already owns $STATE_DIR/daemon.lock."
  exit 0
fi

if [[ ! -x "$CODEX_BIN" ]]; then
  echo "Codex executable not found: $CODEX_BIN" >&2
  exit 1
fi

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "Daemon prompt not found: $PROMPT_FILE" >&2
  exit 1
fi

stop_requested() {
  [[ -f "$STATE_DIR/STOP" ]]
}

while ! stop_requested; do
  if [[ -f "$STATE_DIR/PAUSE" ]]; then
    echo "$(date --iso-8601=seconds) paused"
    sleep 30
    continue
  fi

  cycle_id="$(date +%Y%m%dT%H%M%S)"
  cycle_log="$STATE_DIR/cycle-$cycle_id.log"
  last_message="$STATE_DIR/last-message.md"
  echo "$(date --iso-8601=seconds) starting cycle $cycle_id"

  if timeout --signal=TERM --kill-after=60 "$MAX_CYCLE_SECONDS" \
    "$CODEX_BIN" \
      --ask-for-approval never \
      --sandbox workspace-write \
      --cd "$ROOT" \
      exec \
      --color never \
      --output-last-message "$last_message" \
      - <"$PROMPT_FILE" 2>&1 | tee "$cycle_log"; then
    echo "$(date --iso-8601=seconds) cycle $cycle_id completed"
    delay="$INTERVAL_SECONDS"
  else
    status=${PIPESTATUS[0]}
    echo "$(date --iso-8601=seconds) cycle $cycle_id failed with status $status"
    delay="$ERROR_BACKOFF_SECONDS"
  fi

  ln -sfn "$(basename "$cycle_log")" "$STATE_DIR/latest.log"
  stop_requested && break
  sleep "$delay"
done

echo "$(date --iso-8601=seconds) daemon stopped"
