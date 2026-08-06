#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-create-two-groups-one-called-my-family-and-invit-000.
# Task: Create two groups, one called "My family" and invite all your contacts tagged by "family", another called "Forever 404" and invite all your classmates. For the second group chat, transfer ownership to Schmidt. Then send a message "How about having dinner at my house tonight?" to your classmates group chat.
# The reference actions are LightTalk state changes recorded from a
# successful reference run (14 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
