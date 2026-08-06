#!/usr/bin/env bash
# Oracle for complexmcp-ladhoc-s777-this-is-a-pure-bookkeeping-simulation-over-light-000.
# Task: This is a PURE BOOKKEEPING SIMULATION over LightShop price data. You must NOT purchase anything, must NOT modify any shop, cart, or balance. You may only look up item prices (e.g. via list_items) and, at the very end, send exactly one message.
# The reference actions are LightTalk, LightShop, LightWeather, LightFlight, LightStock, LightNews state changes recorded from a
# successful reference run (17 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightShop, LightWeather, LightFlight, LightStock, LightNews world-state changes required by the task are applied; nothing else is disturbed."
