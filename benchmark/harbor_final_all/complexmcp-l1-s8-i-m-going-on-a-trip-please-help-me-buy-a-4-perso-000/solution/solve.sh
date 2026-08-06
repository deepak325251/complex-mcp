#!/usr/bin/env bash
# Oracle for complexmcp-l1-s8-i-m-going-on-a-trip-please-help-me-buy-a-4-perso-000.
# Task: I’m going on a trip—please help me buy a 4-person tent for the lowest price available.
# The reference actions are LightShop state changes recorded from a
# successful reference run (9 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightShop world-state changes required by the task are applied; nothing else is disturbed."
