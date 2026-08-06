#!/usr/bin/env bash
# Oracle for complexmcp-l1-s1-buy-one-apple-watch-series-9-and-delete-the-tran-000.
# Task: Buy one Apple Watch Series 9 and delete the transaction history.
# The reference actions are LightShop state changes recorded from a
# successful reference run (7 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightShop world-state changes required by the task are applied; nothing else is disturbed."
