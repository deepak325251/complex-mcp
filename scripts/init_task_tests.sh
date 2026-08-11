#!/usr/bin/env bash
# Scaffold a task's tests/ with the canonical grading templates for HAND-AUTHORING.
#
# The USER writes the pytest + rubric that go in the input bundle . This
# copies starter templates so you don't begin from scratch: the accessor header in test_outputs.py
# (dump/old_env/app/collection/find/added — it already unwraps the {status,output} dump envelope and
# reads the in-process $NEW_ENV) is correct-by-construction — DO NOT edit it. You edit only the
# EXAMPLE TESTS below the marker, the weights, and the rubric criteria to fit your task.
#
# Usage: scripts/init_task_tests.sh harbour-task/<task_dir>
set -euo pipefail

TASK="${1:?usage: init_task_tests.sh <task_dir>}"
KIT="$(cd "$(dirname "$0")/.." && pwd)/benchmark/rubric_pytest_kit"
mkdir -p "$TASK/tests"

for f in test_outputs.py test_weights.json rubric.json; do
  if [ -e "$TASK/tests/$f" ]; then
    echo "skip (exists): tests/$f"
  else
    cp "$KIT/templates/$f" "$TASK/tests/$f"
    echo "wrote tests/$f"
  fi
done

echo
echo "Next: edit tests/{test_outputs.py (below the EXAMPLE marker), test_weights.json, rubric.json}"
echo "for your task, then validate:"
echo "  python3 $KIT/qc/no_class_check.py $TASK/tests/test_outputs.py"
echo "  python3 $KIT/qc/channel_check.py  $TASK/tests/test_outputs.py"
