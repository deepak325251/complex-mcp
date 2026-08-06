#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-create-a-group-chat-invite-all-your-neighbors-an-000.
# Task: Create a group chat, invite all your neighbors, and transfer ownership to Silas.
# The reference actions are LightTalk state changes recorded from a
# successful reference run (9 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
