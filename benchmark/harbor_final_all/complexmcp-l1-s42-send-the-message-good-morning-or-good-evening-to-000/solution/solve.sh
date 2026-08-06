#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-send-the-message-good-morning-or-good-evening-to-000.
# Task: Send the message 'Good morning' or 'Good evening' to your classmate Paisley. After that, keep all statuses unchanged in the final version.
# The reference actions are LightTalk, LightShop state changes recorded from a
# successful reference run (13 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightShop world-state changes required by the task are applied; nothing else is disturbed."
