#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-mark-the-messages-from-sean-baker-as-read-000.
# Task: Mark the messages from Sean Baker as read.
# The reference actions are LightTalk, LightShop state changes recorded from a
# successful reference run (2 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightShop world-state changes required by the task are applied; nothing else is disturbed."
