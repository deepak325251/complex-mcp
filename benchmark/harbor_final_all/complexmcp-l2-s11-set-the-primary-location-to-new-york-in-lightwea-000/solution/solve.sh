#!/usr/bin/env bash
# Oracle for complexmcp-l2-s11-set-the-primary-location-to-new-york-in-lightwea-000.
# Task: Set the primary location to 'New York' in LightWeather. Then, check today’s sunset time in primary location and calculate the sun rate as a percentage (rounded to two decimal places). Finally, send the result in the format 'xx.xx%' to your contact Aaliyah Gonzalez on LightTalk.
# The reference actions are LightTalk, LightWeather state changes recorded from a
# successful reference run (11 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightWeather world-state changes required by the task are applied; nothing else is disturbed."
