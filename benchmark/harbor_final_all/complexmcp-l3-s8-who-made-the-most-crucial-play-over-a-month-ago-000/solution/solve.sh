#!/usr/bin/env bash
# Oracle for complexmcp-l3-s8-who-made-the-most-crucial-play-over-a-month-ago-000.
# Task: Who made the most crucial play over a month ago in LightTown High Football's homecoming game? Send his name to contact Judy Bailey on the LightTalk app. Also, I’d like to eat some endive tonight—please buy 0.5 kg for me.
# The reference actions are LightTalk, LightShop, LightNews state changes recorded from a
# successful reference run (11 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightShop, LightNews world-state changes required by the task are applied; nothing else is disturbed."
