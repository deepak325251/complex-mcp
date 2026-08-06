#!/usr/bin/env bash
# Oracle for complexmcp-l1-s8-please-help-me-purchase-1-kilogram-of-mangosteen-000.
# Task: Please help me purchase 1 kilogram of mangosteen and 1 kilogram of mango.
# The reference actions are LightShop state changes recorded from a
# successful reference run (6 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightShop world-state changes required by the task are applied; nothing else is disturbed."
