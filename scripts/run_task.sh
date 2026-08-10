#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

SERVERS_SESSION="omcp-servers-auto"
SOFTS_SESSION="omcp-softs-auto"

cleanup() {
    echo "[run_task] shutting down servers + software..."
    tmux kill-session -t "$SERVERS_SESSION" 2>/dev/null || true
    tmux kill-session -t "$SOFTS_SESSION" 2>/dev/null || true
    lsof -ti:8000-8024,9000-9144 2>/dev/null | xargs -r kill -9 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[run_task] cleaning stale port squatters on 8000-8024, 9000-9144"
lsof -ti:8000-8024,9000-9144 2>/dev/null | xargs -r kill -9 2>/dev/null || true
sleep 1

chmod +x start_servers.sh start_softwares.sh 2>/dev/null || true

echo "[run_task] launching all 20 utility servers in tmux:$SERVERS_SESSION"
tmux new-session -d -s "$SERVERS_SESSION" \
    "cd $REPO_ROOT && source .venv/bin/activate && bash start_servers.sh 2>&1 | tee /tmp/omcp-servers.log"

echo "[run_task] launching all 140 sandbox apps in tmux:$SOFTS_SESSION"
tmux new-session -d -s "$SOFTS_SESSION" \
    "cd $REPO_ROOT && source .venv/bin/activate && zsh start_softwares.sh 2>&1 | tee /tmp/omcp-softs.log"

REQUIRED_PORTS=({8000..8007} {8013..8024} {9000..9008} {9014..9144})
echo "[run_task] waiting up to 240s for ${#REQUIRED_PORTS[@]} required ports..."
ready=0
for i in $(seq 1 240); do
    ready=1
    for p in "${REQUIRED_PORTS[@]}"; do
        python3 -c "import socket; socket.create_connection(('localhost', $p), 1).close()" 2>/dev/null || { ready=0; break; }
    done
    if [ "$ready" -eq 1 ]; then
        echo "[run_task] all ${#REQUIRED_PORTS[@]} ports ready after ${i}s"
        break
    fi
    sleep 1
done

if [ "$ready" -ne 1 ]; then
    echo "[run_task] timeout waiting for ports; showing which ports are missing:" >&2
    for p in "${REQUIRED_PORTS[@]}"; do
        python3 -c "import socket; socket.create_connection(('localhost', $p), 1).close()" 2>/dev/null || echo "  $p DOWN" >&2
    done
    exit 1
fi

MODEL="${MODEL:-claude-opus-4-8}"
METHOD="${METHOD:-rag}"
LIMIT="${LIMIT:-4}"
RUNNER="${RUNNER:-run_benchmark.py}"
CONFIG="${CONFIG:-config/general.yaml}"
TASKS_DIR="${TASKS_DIR:-tasks}"
LAYOUT="${LAYOUT:-mcp-stump}"
if [ "$LAYOUT" = "mcp-stump" ]; then
    OUTPUT_DIR="${OUTPUT_DIR:-output}"
else
    OUTPUT_DIR="${OUTPUT_DIR:-runs}"
fi
BAKE_GT="${BAKE_GT:-0}"

if [ "$BAKE_GT" = "1" ]; then
    echo "[run_task] BAKE_GT=1 -> running scripts/bake_harbor_gt.py first"
    BAKE_CMD=(.venv/bin/python scripts/bake_harbor_gt.py -t "$CONFIG" --tasks-dir "$TASKS_DIR")
    if [ -n "${TASK:-}" ]; then
        BAKE_CMD+=(--task "$TASK")
    elif [ "$LIMIT" -gt 0 ]; then
        BAKE_CMD+=(--limit "$LIMIT")
    fi
    "${BAKE_CMD[@]}"
fi

if [ "$#" -gt 0 ]; then
    echo "[run_task] launching custom command: $*"
    .venv/bin/python "$@"
else
    CMD=(.venv/bin/python "$RUNNER"
         -m "$MODEL"
         --method "$METHOD"
         -t "$CONFIG"
         --tasks-dir "$TASKS_DIR"
         --output-dir "$OUTPUT_DIR"
         --layout "$LAYOUT")
    if [ -n "${TASK:-}" ]; then
        echo "[run_task] launching: $RUNNER --task $TASK"
        CMD+=(--task "$TASK")
    else
        echo "[run_task] launching: $RUNNER --limit $LIMIT"
        CMD+=(--limit "$LIMIT")
    fi
    echo "[run_task] tasks-dir=$TASKS_DIR  output-dir=$OUTPUT_DIR"
    "${CMD[@]}"
fi
