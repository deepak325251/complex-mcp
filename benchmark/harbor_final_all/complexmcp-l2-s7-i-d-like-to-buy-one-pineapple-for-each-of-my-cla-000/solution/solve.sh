#!/usr/bin/env bash
# Oracle for complexmcp-l2-s7-i-d-like-to-buy-one-pineapple-for-each-of-my-cla-000.
# Task: I’d like to buy one pineapple for each of my classmates on LightTalk, including myself—and I want the most expensive ones available.
# The reference actions are LightTalk, LightShop state changes recorded from a
# successful reference run (8 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightShop world-state changes required by the task are applied; nothing else is disturbed."
