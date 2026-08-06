#!/usr/bin/env bash
# Harbor verifier entrypoint.
# Contract: dump the final world state, run the ComplexMCP state-diff grader,
# and write reward to /logs/verifier/reward.json (+ reward.txt fallback).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LOGDIR="${VERIFIER_LOG_DIR:-/logs/verifier}"
mkdir -p "$LOGDIR"

: "${DUMP_URL:=http://localhost:8900/__dump__}"
curl -sf "$DUMP_URL" -o "$HERE/new_env.json" \
  || { echo "ERROR: could not dump world state from $DUMP_URL" >&2; echo 0 > "$LOGDIR/reward.txt"; exit 0; }

export OLD_ENV="$HERE/old_env.json"
export NEW_ENV="$HERE/new_env.json"
export GT_ENV="$HERE/gt_env.json"
export VERIFIER_LOG_DIR="$LOGDIR"

python3 "$HERE/verify.py"
