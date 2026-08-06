#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-change-your-ip-address-to-one-in-new-york-then-p-000.
# Task: Change your IP address to one in New York, then post a Moment with the text: 'Hello, world.'
# The reference actions are LightTalk state changes recorded from a
# successful reference run (8 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
