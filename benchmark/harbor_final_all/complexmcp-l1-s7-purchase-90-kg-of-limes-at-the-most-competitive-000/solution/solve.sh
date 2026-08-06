#!/usr/bin/env bash
# Oracle for complexmcp-l1-s7-purchase-90-kg-of-limes-at-the-most-competitive-000.
# Task: Purchase 90 kg of limes at the most competitive price.
# The reference actions are LightShop state changes recorded from a
# successful reference run (15 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightShop world-state changes required by the task are applied; nothing else is disturbed."
