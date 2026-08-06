#!/usr/bin/env bash
# Oracle for complexmcp-l2-s1-i-would-like-to-book-a-business-class-flight-fro-000.
# Task: I would like to book a business class flight from San Francisco to New York on February 27 for myself.
# The reference actions are LightTalk, LightFlight state changes recorded from a
# successful reference run (3 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightFlight world-state changes required by the task are applied; nothing else is disturbed."
