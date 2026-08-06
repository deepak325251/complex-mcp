#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-convert-16-8-inches-to-centimeters-and-send-the-000.
# Task: Convert 16.8 inches to centimeters and send the result to yourself on LightTalk with no additional text.
# The reference actions are LightTalk state changes recorded from a
# successful reference run (3 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
