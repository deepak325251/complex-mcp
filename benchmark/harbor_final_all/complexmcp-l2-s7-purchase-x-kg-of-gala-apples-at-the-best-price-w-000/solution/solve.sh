#!/usr/bin/env bash
# Oracle for complexmcp-l2-s7-purchase-x-kg-of-gala-apples-at-the-best-price-w-000.
# Task: Purchase x kg of Gala apples at the best price, where x equals the total number of your immediate and extended
# The reference actions are LightTalk, LightShop state changes recorded from a
# successful reference run (0 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightShop world-state changes required by the task are applied; nothing else is disturbed."
