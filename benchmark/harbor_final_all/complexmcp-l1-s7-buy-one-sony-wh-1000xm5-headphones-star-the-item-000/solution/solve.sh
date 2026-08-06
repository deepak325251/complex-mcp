#!/usr/bin/env bash
# Oracle for complexmcp-l1-s7-buy-one-sony-wh-1000xm5-headphones-star-the-item-000.
# Task: Buy one Sony WH-1000XM5 headphones. Star the item.
# The reference actions are LightShop state changes recorded from a
# successful reference run (11 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightShop world-state changes required by the task are applied; nothing else is disturbed."
