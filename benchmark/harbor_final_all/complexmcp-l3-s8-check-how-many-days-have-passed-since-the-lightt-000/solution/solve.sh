#!/usr/bin/env bash
# Oracle for complexmcp-l3-s8-check-how-many-days-have-passed-since-the-lightt-000.
# Task: Check how many days have passed since the LightTown fashion brand was launched. If it has been more than 365 days, buy 2 kg of chickpeas and send a message to your contact Martin in the format: 'days,price'.
# The reference actions are LightTalk, LightShop, LightNews state changes recorded from a
# successful reference run (9 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightShop, LightNews world-state changes required by the task are applied; nothing else is disturbed."
