#!/usr/bin/env bash
# Harbor verifier entrypoint (replaces the state-diff test.sh).
# Contract:
#   1) dump the final world state from the running apps  -> old_env baseline is
#      shipped in the task's tests/ dir (seed-generated once).
#   2) OPTIONAL: judge rubric.json against the agent deliverable (output.md) with an
#      LLM, writing rubric_verdicts.json ({"R1": true, ...}). If your harness has no
#      judge step, skip it and grade.py falls back to Channel A only.
#   3) run grade.py -> reward.json (+ reward.txt) in $VERIFIER_LOG_DIR.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LOGDIR="${VERIFIER_LOG_DIR:-/logs/verifier}"
mkdir -p "$LOGDIR"

: "${DUMP_URL:=http://localhost:8900/__dump__}"
export DUMP_URL
export OLD_ENV="${OLD_ENV:-$HERE/old_env.json}"
export TESTS_PY="${TESTS_PY:-$HERE/test_outputs.py}"
export WEIGHTS_JSON="${WEIGHTS_JSON:-$HERE/test_weights.json}"
export RUBRIC_JSON="${RUBRIC_JSON:-$HERE/rubric.json}"
export RUBRIC_VERDICTS="${RUBRIC_VERDICTS:-$HERE/rubric_verdicts.json}"
export VERIFIER_LOG_DIR="$LOGDIR"

# Fail closed: if the world state can't be dumped, reward 0 and exit clean.
if ! curl -sf "$DUMP_URL" -o /dev/null; then
  echo "ERROR: could not reach world dump at $DUMP_URL" >&2
  echo 0 > "$LOGDIR/reward.txt"
  echo '{"reward": 0, "error": "dump_unreachable"}' > "$LOGDIR/reward.json"
  exit 0
fi

# 2) rubric judging is harness-specific; drop rubric_verdicts.json in $HERE before
#    this step to include Channel B. (See GENERATOR.md "Judging the rubric".)

python3 "$HERE/grade.py"
