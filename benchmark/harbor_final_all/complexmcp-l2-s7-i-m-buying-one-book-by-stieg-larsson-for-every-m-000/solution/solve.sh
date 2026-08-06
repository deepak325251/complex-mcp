#!/usr/bin/env bash
# Oracle for complexmcp-l2-s7-i-m-buying-one-book-by-stieg-larsson-for-every-m-000.
# Task: I’m buying one book by Stieg Larsson for every member of my team, including myself.
# The reference actions are LightTalk, LightShop state changes recorded from a
# successful reference run (10 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightShop world-state changes required by the task are applied; nothing else is disturbed."
