#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

OUT_DIR="${1:-/tmp/harbor-cmcp-smoke}"
LIMIT="${LIMIT:-1}"
HOST_MODE="${HOST_MODE:-host}"

PYTHON="${PYTHON:-.venv/bin/python}"

if ! [ -x "$PYTHON" ]; then
    echo "no python at $PYTHON (set PYTHON=/path/to/python)" >&2
    exit 1
fi

echo "[smoke] python              = $PYTHON"
echo "[smoke] output_dir          = $OUT_DIR"
echo "[smoke] limit               = $LIMIT"
echo "[smoke] host_mode           = $HOST_MODE"
echo

rm -rf "$OUT_DIR"

PYTHONPATH="$REPO_ROOT/harbor/adapters/complex-mcp/src" \
    "$PYTHON" -m complex_mcp.main \
        --output-dir "$OUT_DIR" \
        --limit "$LIMIT" \
        --host-mode "$HOST_MODE" \
        --overwrite

echo
echo "[smoke] generated tasks:"
ls -1 "$OUT_DIR"

FIRST_TASK="$(ls -1 "$OUT_DIR" | head -n1)"
echo
echo "[smoke] contents of $FIRST_TASK:"
find "$OUT_DIR/$FIRST_TASK" -type f | sort

echo
echo "[smoke] task.toml:"
cat "$OUT_DIR/$FIRST_TASK/task.toml"

echo
echo "[smoke] instruction.md (first 40 lines):"
head -n 40 "$OUT_DIR/$FIRST_TASK/instruction.md"

echo
echo "[smoke] task_meta.json:"
cat "$OUT_DIR/$FIRST_TASK/data/task_meta.json"

echo
echo "[smoke] OK"
