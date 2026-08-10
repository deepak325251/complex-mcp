"""Weighted rubric scoring for benchmark tasks.

A rubric.json lives beside a task and encodes checks the grader wants to
apply on top of (or instead of) env-state diff. Each check has a weight;
weights should sum to 1.0. The final rubric_score is the sum of weights
for checks that passed, i.e. it always lies in [0, 1].

Rubric schema
-------------
{
  "checks": [
    {
      "check_id": "called_get_uid",
      "weight": 0.25,
      "check_type": "tool_called",
      "tool_name": "get_uid_from_name",
      "min_calls": 1
    },
    {
      "check_id": "liked_target_moment",
      "weight": 0.5,
      "check_type": "tool_called",
      "tool_name": "like_moment",
      "min_calls": 1,
      "args_include": {"user_id": "user_KE9GL2kCPiWqo6s43vsaai"}
    },
    {
      "check_id": "no_extra_writes",
      "weight": 0.25,
      "check_type": "state_predicate",
      "predicate": "misbehave_leq",
      "value": 0
    }
  ]
}

check_type values
-----------------
- ``tool_called``: PASS iff the trajectory shows at least ``min_calls``
  invocations of ``tool_name`` (default 1). Optional ``args_include``
  is a dict of arg-name → expected-value that must appear (equality) in
  the tool call arguments.
- ``state_predicate``: PASS iff a named predicate evaluates true against
  the score dict (recall/misbehave/etc). Supported predicates:
    - ``misbehave_leq`` (with ``value``): ``score['misbehave'] <= value``
    - ``recall_geq`` (with ``value``): ``score['recall'] >= value``
    - ``reward_geq`` (with ``value``): ``score['reward'] >= value``
    - ``passed_true``: ``score['passed']`` is truthy

Anything unrecognized fails with a reason set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    check_id: str
    weight: float
    passed: bool
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _check_tool_called(check: dict, trajectory: dict) -> tuple[bool, str]:
    tool_name = check.get("tool_name")
    if not tool_name:
        return False, "check missing 'tool_name'"
    min_calls = int(check.get("min_calls", 1))
    args_include = check.get("args_include") or {}

    matches = 0
    for step in trajectory.get("steps", []):
        if step.get("tool") != tool_name:
            continue
        if args_include:
            step_args = step.get("arguments") or {}
            if not isinstance(step_args, dict):
                continue
            if not all(step_args.get(k) == v for k, v in args_include.items()):
                continue
        matches += 1

    if matches >= min_calls:
        return True, f"{tool_name} called {matches} time(s) (>= {min_calls})"
    return False, f"{tool_name} called {matches} time(s), need {min_calls}"


def _check_state_predicate(check: dict, score: dict) -> tuple[bool, str]:
    pred = check.get("predicate")
    value = check.get("value")
    if pred == "misbehave_leq":
        actual = score.get("misbehave")
        if actual is None:
            return False, "misbehave not in score"
        ok = int(actual) <= int(value)
        return ok, f"misbehave={actual} vs <= {value}"
    if pred == "recall_geq":
        actual = score.get("recall")
        if actual is None:
            return False, "recall not in score"
        ok = int(actual) >= int(value)
        return ok, f"recall={actual} vs >= {value}"
    if pred == "reward_geq":
        actual = score.get("reward")
        if actual is None:
            return False, "reward not in score"
        ok = float(actual) >= float(value)
        return ok, f"reward={actual} vs >= {value}"
    if pred == "passed_true":
        return bool(score.get("passed")), f"passed={score.get('passed')}"
    return False, f"unknown predicate {pred!r}"


def evaluate_rubric(
    rubric: dict,
    trajectory: dict,
    score: dict | None = None,
) -> dict:
    checks = rubric.get("checks") or []
    if not checks:
        return {"rubric_score": 0.0, "per_check": [], "reason": "empty rubric"}

    total_weight = sum(float(c.get("weight", 0.0)) for c in checks)
    normalize = total_weight > 0 and abs(total_weight - 1.0) > 0.001

    per_check: list[dict] = []
    earned = 0.0
    for check in checks:
        check_id = str(check.get("check_id") or f"check_{len(per_check)}")
        weight = float(check.get("weight", 0.0))
        if normalize:
            weight = weight / total_weight
        ct = check.get("check_type")
        if ct == "tool_called":
            passed, reason = _check_tool_called(check, trajectory)
        elif ct == "state_predicate":
            passed, reason = _check_state_predicate(check, score or {})
        else:
            passed, reason = False, f"unknown check_type {ct!r}"
        if passed:
            earned += weight
        per_check.append(
            CheckResult(check_id=check_id, weight=weight,
                        passed=passed, reason=reason).to_dict()
        )

    return {"rubric_score": round(earned, 4), "per_check": per_check}


def load_rubric(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}")


def find_rubric_for_task(task_dir: str | Path | None) -> Path | None:
    if not task_dir:
        return None
    p = Path(task_dir) / "rubric.json"
    return p if p.exists() else None
