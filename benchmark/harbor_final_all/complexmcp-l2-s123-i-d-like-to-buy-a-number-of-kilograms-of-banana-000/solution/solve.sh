#!/usr/bin/env bash
# Oracle for complexmcp-l2-s123-i-d-like-to-buy-a-number-of-kilograms-of-banana-000.
# Task: I’d like to buy a number of kilograms of banana peppers equal to the number of my neighbors.
# The reference actions are LightTalk, LightShop state changes recorded from a
# successful reference run (0 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightShop world-state changes required by the task are applied; nothing else is disturbed."
