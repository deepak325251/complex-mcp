#!/usr/bin/env bash
# Start (daemonize) the 6 servers the auth-v2 task needs, seed-pinned to 2216.
# Uses nohup+setsid so they survive this script exiting AND the terminal closing.
# Re-running is safe: it skips ports already listening.
#
#   ./scripts/serve_auth_v2.sh          # start + wait until all six bind
#   ./scripts/serve_auth_v2.sh stop     # kill them
set -u
cd "$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$PWD"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
FM="$ROOT/.venv/bin/fastmcp"
SEED="${COMPLEXMCP_SEED:-2216}"

APPS=(LightSystem:9000 LightJira:9086 LightNotion:9099 LightConfluence:9060 LightGithub:9072 LightSlack:9119)

port_pid() { lsof -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }

if [ "${1:-start}" = "stop" ]; then
  for spec in "${APPS[@]}"; do
    p="${spec##*:}"; pid="$(port_pid "$p")"
    [ -n "$pid" ] && { kill "$pid" 2>/dev/null; echo "stopped $spec (pid $pid)"; } || echo "$spec already down"
  done
  exit 0
fi

echo "Starting auth-v2 servers (seed=$SEED) ..."
for spec in "${APPS[@]}"; do
  app="${spec%%:*}"; port="${spec##*:}"
  if [ -n "$(port_pid "$port")" ]; then echo "  $app :$port already up"; continue; fi
  COMPLEXMCP_SEED="$SEED" nohup "$FM" run "software/$app/app.py" \
      --transport http --host 0.0.0.0 --port "$port" >"/tmp/$app.log" 2>&1 < /dev/null &
  disown 2>/dev/null || true
done

echo "Waiting for all ports to bind ..."
ok=1
for spec in "${APPS[@]}"; do
  app="${spec%%:*}"; port="${spec##*:}"
  for _ in $(seq 1 60); do [ -n "$(port_pid "$port")" ] && break; sleep 0.5; done
  if [ -n "$(port_pid "$port")" ]; then echo "  $app :$port UP"; else echo "  $app :$port DOWN (see /tmp/$app.log)"; ok=0; fi
done
[ "$ok" = 1 ] && echo "All six up. Servers keep running after this exits." || { echo "Some failed — check /tmp/*.log"; exit 1; }
