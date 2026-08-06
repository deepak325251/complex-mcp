#!/usr/bin/env bash
# Oracle for complexmcp-l1-s12-post-to-your-lighttalk-moments-containing-only-t-000.
# Task: Post to your LightTalk moments, containing only the SHA-256 hash of your UID.
# The reference actions are LightTalk state changes recorded from a
# successful reference run (5 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
