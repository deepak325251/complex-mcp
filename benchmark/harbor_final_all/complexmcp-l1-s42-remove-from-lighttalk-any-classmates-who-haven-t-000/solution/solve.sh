#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-remove-from-lighttalk-any-classmates-who-haven-t-000.
# Task: Remove from LightTalk any classmates who haven’t chatted with you since 2024.
# The reference actions are LightTalk state changes recorded from a
# successful reference run (15 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
