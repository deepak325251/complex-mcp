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

# WORLD_DATA (dir of <AppName>.json files, software.utils.world_data) must be
# exported *before* the sandbox app servers are forked, not just passed to
# run_benchmark.py later -- those servers are long-lived processes started
# here in tmux, and each app's hydrate() call reads COMPLEXMCP_WORLD_DATA from
# its own process env at session-login time. Setting the var only inside
# run_benchmark.py's process (e.g. via --world-data) never reaches these
# already-forked servers, so the live agent would silently keep talking to
# the normal seeded world while only in-process grading/baking saw the world
# data -- a split-brain that trips the state-admissibility guard. Exporting
# it here, before both tmux launches, makes the live servers and the grading
# side agree.
COMPLEXMCP_WORLD_DATA=""
if [ -n "${WORLD_DATA:-}" ]; then
    COMPLEXMCP_WORLD_DATA="$(cd "$WORLD_DATA" && pwd)"
    export COMPLEXMCP_WORLD_DATA
    echo "[run_task] COMPLEXMCP_WORLD_DATA=$COMPLEXMCP_WORLD_DATA (exported to sandbox servers)"
fi
# Injected into the tmux command strings explicitly (not relied on via plain
# env inheritance): if a tmux *server* is already running from an earlier
# invocation, `tmux new-session` on it reuses that server's own captured
# environment rather than this script's -- an inline assignment in the
# command string is unconditionally reliable either way.

echo "[run_task] launching all 20 utility servers in tmux:$SERVERS_SESSION"
tmux new-session -d -s "$SERVERS_SESSION" \
    "cd $REPO_ROOT && source .venv/bin/activate && COMPLEXMCP_WORLD_DATA='$COMPLEXMCP_WORLD_DATA' bash start_servers.sh 2>&1 | tee /tmp/omcp-servers.log"

echo "[run_task] launching all 140 sandbox apps in tmux:$SOFTS_SESSION"
tmux new-session -d -s "$SOFTS_SESSION" \
    "cd $REPO_ROOT && source .venv/bin/activate && COMPLEXMCP_WORLD_DATA='$COMPLEXMCP_WORLD_DATA' zsh start_softwares.sh 2>&1 | tee /tmp/omcp-softs.log"

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
# harbor is the delivered format (output/<task>/trajectory/Run_N/...). The older
# mcp-stump tree is still produced inside it under .raw/, and is selectable on
# its own with LAYOUT=mcp-stump.
LAYOUT="${LAYOUT:-harbor}"
# Both mcp-stump and harbor write under output/; only the legacy layout uses runs/.
if [ "$LAYOUT" = "mcp-stump" ] || [ "$LAYOUT" = "harbor" ]; then
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
    if [ "${NATIVE:-0}" = "1" ]; then
        CMD+=(--native-tools)
        echo "[run_task] NATIVE=1 -> using native function-calling (OpenAIBackend / proxy)"
    fi
    if [ -n "${TOPK:-}" ]; then
        CMD+=(--topk "$TOPK")
        echo "[run_task] TOPK=$TOPK"
    fi
    if [ -n "${GRADER:-}" ]; then
        CMD+=(--grader "$GRADER")
        echo "[run_task] GRADER=$GRADER"
    fi
    if [ -n "${WORLD_DATA:-}" ]; then
        # Same dir the sandbox servers were exported above -- keeps
        # run_benchmark.py's in-process baking/repair consistent with what
        # the live servers actually served, instead of the two diverging.
        CMD+=(--world-data "$COMPLEXMCP_WORLD_DATA")
        echo "[run_task] WORLD_DATA=$COMPLEXMCP_WORLD_DATA"
    fi
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
