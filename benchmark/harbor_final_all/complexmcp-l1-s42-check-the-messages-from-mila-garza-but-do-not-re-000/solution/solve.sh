#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-check-the-messages-from-mila-garza-but-do-not-re-000.
# Task: Check the messages from Mila Garza, but do not reply—only mark her messages as unread.
# The reference actions are LightTalk state changes recorded from a
# successful reference run (3 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
