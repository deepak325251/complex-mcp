#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-like-the-latest-post-in-jeremy-guzman-s-moments-000.
# Task: Like the latest post in Jeremy Guzman's Moments on LightTalk.
# The reference actions are LightTalk state changes recorded from a
# successful reference run (6 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
