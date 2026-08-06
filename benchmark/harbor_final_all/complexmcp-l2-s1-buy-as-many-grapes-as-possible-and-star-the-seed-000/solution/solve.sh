#!/usr/bin/env bash
# Oracle for complexmcp-l2-s1-buy-as-many-grapes-as-possible-and-star-the-seed-000.
# Task: Buy as many grapes as possible, and star the seedless variety along with its shop.
# The reference actions are LightShop state changes recorded from a
# successful reference run (13 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightShop world-state changes required by the task are applied; nothing else is disturbed."
