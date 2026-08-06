#!/usr/bin/env bash
# Oracle for complexmcp-l1-s42-send-jonah-palmer-the-contact-sharing-link-for-y-000.
# Task: Send Jonah Palmer the contact sharing link for your classmate Dennis. The message must strictly follow this format:
# The reference actions are LightTalk state changes recorded from a
# successful reference run (10 tool calls). trajectory.json holds the
# gold tool chain (tool + args + purpose) in execution order.
set -euo pipefail
echo "Reference trajectory in $(dirname "$0")/trajectory.json"
echo "Net effect: the LightTalk world-state changes required by the task are applied; nothing else is disturbed."
