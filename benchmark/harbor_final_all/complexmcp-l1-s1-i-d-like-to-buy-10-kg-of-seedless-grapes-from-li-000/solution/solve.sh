#!/usr/bin/env bash
# Oracle for complexmcp-l1-s1-i-d-like-to-buy-10-kg-of-seedless-grapes-from-li-000.
# Task: I’d like to buy 10 kg of seedless grapes from LightShop.
# The reference actions are LightShop state changes recorded from a
# successful reference run (12 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightShop world-state changes required by the task are applied; nothing else is disturbed."
