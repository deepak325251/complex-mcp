"""Weighted rubric scoring for benchmark tasks.

Two rubric formats are supported.

FORMAT 1 — dict-with-checks (deterministic)
-------------------------------------------
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

check_type values:
- ``tool_called``: PASS iff trajectory shows at least ``min_calls`` invocations of
  ``tool_name`` (default 1). Optional ``args_include`` is a dict of
  arg-name → expected-value that must appear in the tool call arguments.
- ``state_predicate``: PASS iff a named predicate evaluates true against the
  score dict (recall/misbehave/reward/passed).

FORMAT 2 — bare-list (mcp-stump; LLM-graded)
--------------------------------------------
[
  {
    "number": "1",
    "criterion": "The agent stated which weather branch it took and why...",
    "type": "reasoning_quality",
    "evaluation_target": "final_answer",   // or "trajectory"
    "importance": "critical",              // or "important" | "moderate"
    "score": 3,                            // 1 | 2 | 3 — weight
    "is_positive": true                    // false => guard/defect check
  }
]

Rc (completion_rate) = Σ(score for positive PASSED) / Σ(score for positive).
Rb (misbehaving_rate) = Σ(score for negative HIT) / Σ(score for negative).
rubric_score = Rc * (1 - Rb), passed = (Rc == 1.0) AND (Rb == 0.0).

Each criterion is graded by a caller-supplied ``llm_grader(criterion, context) → (bool, str)``.
If none is provided the default shells out to the ``claude`` CLI. Tests pass a stub grader.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable


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


def _evaluate_dict_rubric(
    rubric: dict,
    trajectory: dict,
    score: dict | None,
) -> dict:
    checks = rubric.get("checks") or []
    if not checks:
        return {"rubric_score": 0.0, "per_check": [], "reason": "empty rubric",
                "format": "dict"}

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

    return {"rubric_score": round(earned, 4), "per_check": per_check,
            "format": "dict"}


def _render_trajectory_for_llm(trajectory: dict, max_chars: int = 12000) -> str:
    parts: list[str] = []
    for step in trajectory.get("steps", []):
        args = step.get("arguments")
        resp = step.get("response")
        args_s = json.dumps(args, ensure_ascii=False)[:500] if not isinstance(args, str) else args[:500]
        resp_s = json.dumps(resp, ensure_ascii=False)[:500] if not isinstance(resp, str) else resp[:500]
        parts.append(f"Step {step.get('step')}: tool={step.get('tool')} args={args_s} → {resp_s}")
    final = trajectory.get("final_message") or ""
    if final:
        parts.append(f"Final: {final[:2000]}")
    joined = "\n".join(parts)
    if len(joined) > max_chars:
        joined = joined[:max_chars] + "\n... [truncated]"
    return joined


_YESNO_RE = re.compile(r"\b(YES|NO)\b", re.IGNORECASE)


def _default_llm_grader(criterion: str, context: str,
                        model: str = "claude-opus-4-8",
                        timeout: int = 90) -> tuple[bool, str]:
    prompt = (
        "You are grading one criterion for an AI agent's trial output.\n"
        "Answer strictly YES or NO on the first line, then a one-sentence "
        "justification on the next line.\n\n"
        f"CRITERION: {criterion}\n\n"
        f"CONTEXT:\n{context}\n"
    )
    claude_bin = os.environ.get("CLAUDE_BIN", "claude")
    cmd = [claude_bin, "-p", "--model", model,
           "--output-format", "json",
           "--dangerously-skip-permissions"]
    try:
        proc = subprocess.run(cmd, input=prompt.encode("utf-8"),
                              capture_output=True, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, f"grader error: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return False, f"grader exit {proc.returncode}: {proc.stderr.decode('utf-8', 'replace')[:200]}"
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return False, "grader returned non-JSON"
    text = data.get("result") or data.get("content") or ""
    if not isinstance(text, str):
        text = str(text)
    m = _YESNO_RE.search(text)
    if not m:
        return False, f"no YES/NO in grader output: {text[:200]}"
    verdict = m.group(1).upper() == "YES"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    justification = lines[1] if len(lines) > 1 else text[:200]
    return verdict, justification


def _evaluate_mcp_stump_rubric(
    criteria: list[dict],
    trajectory: dict,
    final_message: str | None,
    llm_grader: Callable[[str, str], tuple[bool, str]],
) -> dict:
    per_criterion: list[dict] = []
    pos_total = 0.0
    pos_earned = 0.0
    neg_total = 0.0
    neg_hit = 0.0

    trajectory_ctx = _render_trajectory_for_llm(trajectory)
    final_ctx = (final_message or "").strip() or "(no final message)"

    for c in criteria:
        weight = float(c.get("score", 1))
        target = c.get("evaluation_target", "final_answer")
        context = final_ctx if target == "final_answer" else trajectory_ctx
        criterion_text = c.get("criterion") or ""
        satisfied, justification = llm_grader(criterion_text, context)
        is_pos = bool(c.get("is_positive", True))
        if is_pos:
            pos_total += weight
            if satisfied:
                pos_earned += weight
        else:
            neg_total += weight
            if satisfied:
                neg_hit += weight
        per_criterion.append({
            "number": c.get("number"),
            "criterion": criterion_text,
            "type": c.get("type"),
            "evaluation_target": target,
            "importance": c.get("importance"),
            "weight": weight,
            "is_positive": is_pos,
            "satisfied": bool(satisfied),
            "justification": justification,
        })

    rc = (pos_earned / pos_total) if pos_total else 1.0
    rb = (neg_hit / neg_total) if neg_total else 0.0
    rubric_passed = (rc >= 0.999999) and (rb <= 0.000001)
    rubric_score = rc * (1.0 - rb)

    # Expose only rc/rb here. The `completion_rate`/`misbehaving_rate` names are
    # owned by the state-diff judge (recall/misbehave over scored key-paths);
    # emitting rb under `misbehaving_rate` too made the same name mean two things
    # across report.json vs rubric.json (a ~44x divergence for one run).
    return {
        "rubric_score": round(rubric_score, 4),
        "rc": round(rc, 4),
        "rb": round(rb, 4),
        "rubric_passed": rubric_passed,
        "per_criterion": per_criterion,
        "format": "mcp-stump",
    }


def evaluate_rubric(
    rubric: dict | list,
    trajectory: dict,
    score: dict | None = None,
    *,
    final_message: str | None = None,
    llm_grader: Callable[[str, str], tuple[bool, str]] | None = None,
) -> dict:
    if isinstance(rubric, list):
        grader = llm_grader or _default_llm_grader
        return _evaluate_mcp_stump_rubric(rubric, trajectory, final_message, grader)
    return _evaluate_dict_rubric(rubric, trajectory, score)


def load_rubric(path: Path) -> dict | list | None:
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
