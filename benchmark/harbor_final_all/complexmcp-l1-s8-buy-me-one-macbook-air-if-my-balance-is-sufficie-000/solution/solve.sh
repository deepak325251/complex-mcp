#!/usr/bin/env bash
# Oracle for complexmcp-l1-s8-buy-me-one-macbook-air-if-my-balance-is-sufficie-000.
# Task: Buy me one MacBook Air if my balance is sufficient.
# The reference actions are LightShop state changes recorded from a
# successful reference run (5 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightShop world-state changes required by the task are applied; nothing else is disturbed."
