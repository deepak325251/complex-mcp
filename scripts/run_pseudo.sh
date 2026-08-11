#!/usr/bin/env bash
# ETOM pseudo-execution runner -- NO sandbox, NO world, NO 160 ports.
#
# In ETOM mode the agent never executes against a live app: every tool call
# returns a schema-shaped pseudo output (client/pseudo_exec.py), login/logout are
# short-circuited, and grading is the tool DAG alone (benchmark/graph_judge vs the
# task's solution/trajectory.json). So the only thing that has to be running is
# the LLM proxy (claude-code-api on :8100) when NATIVE=1.
#
# Usage:
#   TASK=05-margin-liquidation TASKS_DIR=standard bash scripts/run_pseudo.sh
#
# Env knobs (all optional):
#   MODEL=claude-opus-4-8  METHOD=list_all  TASKS_DIR=standard  TASK=<name>
#   NATIVE=1 (default; needs the proxy)     OUTPUT_DIR=output_pseudo
#   CONFIG=config/general.yaml              LAYOUT=mcp-stump   LIMIT=4
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

export ETOM_PSEUDO=1                      # <-- the switch: world-free execution

MODEL="${MODEL:-claude-opus-4-8}"
METHOD="${METHOD:-list_all}"              # pseudo needs the tools listed, not RAG
CONFIG="${CONFIG:-config/general.yaml}"
TASKS_DIR="${TASKS_DIR:-standard}"
LAYOUT="${LAYOUT:-mcp-stump}"
OUTPUT_DIR="${OUTPUT_DIR:-output_pseudo}"
LIMIT="${LIMIT:-4}"
NATIVE="${NATIVE:-1}"

echo "[run_pseudo] ETOM_PSEUDO=1 -- no sandbox ports are booted; grading = tool DAG (graph)."
if [ "$NATIVE" = "1" ]; then
    echo "[run_pseudo] NATIVE=1 -> LLM via proxy (ensure claude-code-api is up on :8100)"
fi

CMD=(.venv/bin/python run_benchmark.py
     -m "$MODEL"
     --method "$METHOD"
     -t "$CONFIG"
     --tasks-dir "$TASKS_DIR"
     --output-dir "$OUTPUT_DIR"
     --layout "$LAYOUT"
     --grader graph)
[ "$NATIVE" = "1" ] && CMD+=(--native-tools)
if [ -n "${TASK:-}" ]; then
    CMD+=(--task "$TASK")
    echo "[run_pseudo] task=$TASK  tasks-dir=$TASKS_DIR  output-dir=$OUTPUT_DIR"
else
    CMD+=(--limit "$LIMIT")
    echo "[run_pseudo] limit=$LIMIT  tasks-dir=$TASKS_DIR  output-dir=$OUTPUT_DIR"
fi

"${CMD[@]}"
