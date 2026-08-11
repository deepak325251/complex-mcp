#!/bin/bash
# Launch the vendored ccbridge (Claude Code OAuth -> raw Anthropic Messages API).
#
# Why: driving the agent through this bridge instead of `claude -p` gives full,
# UN-redacted extended-thinking (text + signatures) on a Max/Pro subscription --
# the raw /v1/messages API does not redact thinking; the CLI headless path does.
#
# Credentials (priority order, see vendor/ccbridge/claude_oauth/credentials.py):
#   1. CLAUDE_CODE_CREDENTIALS  inline JSON  {"claudeAiOauth":{"accessToken":...}}
#   2. WCB_CC_CREDS_PATH        path to a credentials JSON file
#   3. ~/.claude/.credentials.json
#   ... (macOS Keychain, etc.)
#
# Usage:
#   export CLAUDE_CODE_CREDENTIALS='{"claudeAiOauth":{...your Max token...}}'
#   scripts/start_ccbridge.sh                 # :8765, locked with a random secret
#   BRIDGE_PORT=8765 scripts/start_ccbridge.sh --check   # verify creds and exit
#
# It prints the exact client wiring (ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY) to use.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PORT="${BRIDGE_PORT:-8765}"
HOST="${BRIDGE_HOST:-127.0.0.1}"
PY="${PY:-.venv/bin/python}"

# Lock the bridge so only clients that know the secret can spend the subscription.
# Reuse an explicit WCB_CC_BRIDGE_SECRET if the caller set one; else generate one.
if [ -z "${WCB_CC_BRIDGE_SECRET:-}" ]; then
    WCB_CC_BRIDGE_SECRET="$("$PY" -c 'import secrets; print(secrets.token_hex(16))')"
fi
export WCB_CC_BRIDGE_SECRET

echo "[ccbridge] starting on http://${HOST}:${PORT}"
echo "[ccbridge] point the runner at it with:"
echo "    export ANTHROPIC_BASE_URL=http://${HOST}:${PORT}"
echo "    export ANTHROPIC_API_KEY=${WCB_CC_BRIDGE_SECRET}"
echo "    unset  CLAUDE_CODE_OAUTH_TOKEN"
echo

PYTHONPATH="vendor/ccbridge${PYTHONPATH:+:$PYTHONPATH}" \
    exec "$PY" -m claude_oauth --host "$HOST" --port "$PORT" "$@"
