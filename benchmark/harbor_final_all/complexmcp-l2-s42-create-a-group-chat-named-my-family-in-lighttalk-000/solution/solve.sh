#!/usr/bin/env bash
# Oracle for complexmcp-l2-s42-create-a-group-chat-named-my-family-in-lighttalk-000.
# Task: Create a group chat named 'My Family' in LightTalk and invite all your family members. Then, purchase one AirPods at the lowest available price and send the message 'I spent $xxx to buy one AirPods' to your family group chat.
# The reference actions are LightTalk, LightShop state changes recorded from a
# successful reference run (17 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk, LightShop world-state changes required by the task are applied; nothing else is disturbed."
