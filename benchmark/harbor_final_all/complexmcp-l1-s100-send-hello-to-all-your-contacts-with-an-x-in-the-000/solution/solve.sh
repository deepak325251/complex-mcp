#!/usr/bin/env bash
# Oracle for complexmcp-l1-s100-send-hello-to-all-your-contacts-with-an-x-in-the-000.
# Task: Send "Hello" to all your contacts with an 'x' in their name.
# The reference actions are LightTalk state changes recorded from a
# successful reference run (12 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
