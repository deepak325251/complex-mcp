#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-what-is-the-greatest-common-divisor-of-121312-an-000.
# Task: What is the greatest common divisor of 121312 and 123178? Send the result to Hayden Parker with no additional text.
# The reference actions are LightTalk state changes recorded from a
# successful reference run (3 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
