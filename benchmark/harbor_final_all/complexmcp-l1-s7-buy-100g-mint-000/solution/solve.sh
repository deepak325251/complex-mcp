#!/usr/bin/env bash
# Oracle for complexmcp-l1-s7-buy-100g-mint-000.
# Task: Buy 100g mint.
# The reference actions are LightShop state changes recorded from a
# successful reference run (4 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightShop world-state changes required by the task are applied; nothing else is disturbed."
