"""Pytest + Rubric grader (trajectory-based) — replaces snapshot state-diff.

Channel A (deterministic): run the task's tests/test_outputs.py under pytest,
with the agent's TRAJECTORY staged at $COMPLEXMCP_TRAJECTORY. Each test maps to a
weight in test_weights.json:

    A = max(0, (Σ passed-positive-w − Σ |triggered-guard-w|) / Σ positive-w)

Channel B (LLM-judged): tests/rubric.json criteria graded against the agent's
final deliverable via a caller-supplied `rubric_judge(criteria, text)->{num:bool}`
(absent → Channel B skipped).

reward = 1.0 iff A ≥ a_threshold AND (rubric is None OR rubric ≥ b_threshold).
`recall`/`total`/`misbehave` come from Channel A so the existing completion /
misbehave-rate aggregates keep working: total = #positive tests, recall =
positives passed, misbehave = guards triggered.
"""

from __future__ import annotations

import json
import os
import tempfile


def _run_pytest_over_trajectory(test_file: str, weights: dict, trajectory: dict) -> dict:
    import pytest

    passed: dict[str, bool] = {}

    class _Collector:
        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                passed[report.nodeid.split("::")[-1]] = report.passed

    with tempfile.TemporaryDirectory() as tmp:
        tpath = os.path.join(tmp, "trajectory.json")
        with open(tpath, "w") as fh:
            json.dump(trajectory or {"steps": [], "final_message": ""}, fh)

        prev = os.environ.get("COMPLEXMCP_TRAJECTORY")
        os.environ["COMPLEXMCP_TRAJECTORY"] = tpath
        # traj_asserts caches the loaded file per-process; clear it each run.
        try:
            from benchmark import traj_asserts
            traj_asserts._CACHE.clear()
        except Exception:
            pass
        try:
            pytest.main([test_file, "-q", "-p", "no:cacheprovider",
                         "--import-mode=importlib"], plugins=[_Collector()])
        finally:
            if prev is None:
                os.environ.pop("COMPLEXMCP_TRAJECTORY", None)
            else:
                os.environ["COMPLEXMCP_TRAJECTORY"] = prev

    pos_total = sum(w for w in weights.values() if w > 0)
    earned = penalty = 0.0
    recall = total = misbehave = 0
    for name, w in weights.items():
        ok = passed.get(name, False)
        if w > 0:
            total += 1
            if ok:
                earned += w
                recall += 1
        else:  # guard: passing means the forbidden thing happened
            if ok:
                penalty += abs(w)
                misbehave += 1
    score = max(0.0, (earned - penalty) / pos_total) if pos_total else 0.0
    return {
        "pytest_score": round(score, 4),
        "recall": recall, "total": total, "misbehave": misbehave,
        "passed_tests": passed,
        "earned": earned, "penalty": penalty, "positive_total": pos_total,
    }


def _score_rubric(criteria: list[dict], verdicts: dict) -> tuple[float | None, list[dict]]:
    pos_total = sum(c["score"] for c in criteria if c["score"] > 0)
    met = penalty = 0.0
    per = []
    for c in criteria:
        v = verdicts.get(c.get("number"))
        per.append({"number": c.get("number"), "criterion": c.get("criterion"),
                    "is_positive": c.get("is_positive", True), "score": c.get("score"),
                    "satisfied": bool(v)})
        if v is None or not v:
            continue
        if c["score"] > 0:
            met += c["score"]
        else:
            penalty += abs(c["score"])
    if not pos_total:
        return None, per
    return round(max(0.0, (met - penalty) / pos_total), 4), per


def judge_trajectory_pytest(trajectory: dict, grading_dir: str, *,
                            final_message: str | None = None,
                            rubric_judge=None,
                            a_threshold: float = 1.0, b_threshold: float = 0.5,
                            verbose: bool = False) -> dict:
    """Grade one run from its trajectory. `grading_dir` holds test_outputs.py +
    test_weights.json (+ optional rubric.json)."""
    test_file = os.path.join(grading_dir, "test_outputs.py")
    weights = json.load(open(os.path.join(grading_dir, "test_weights.json"), encoding="utf-8"))
    a = _run_pytest_over_trajectory(test_file, weights, trajectory)

    rubric_score = None
    rubric_per_criterion = None
    # rubric.json may live in tests/ (grading_dir) OR at the task root (its parent).
    rubric_path = os.path.join(grading_dir, "rubric.json")
    if not os.path.exists(rubric_path):
        rubric_path = os.path.join(os.path.dirname(grading_dir.rstrip("/")), "rubric.json")
    if rubric_judge is not None and os.path.exists(rubric_path):
        rubric = json.load(open(rubric_path, encoding="utf-8"))
        criteria = rubric.get("criteria", rubric) if isinstance(rubric, dict) else rubric
        verdicts = rubric_judge(criteria, final_message or "")
        rubric_score, rubric_per_criterion = _score_rubric(criteria, verdicts)

    passed = int(a["pytest_score"] >= a_threshold
                 and (rubric_score is None or rubric_score >= b_threshold))
    result = {
        "reward": 1.0 if passed else 0.0,
        "passed": bool(passed),
        "pytest_score": a["pytest_score"],
        "rubric_score": rubric_score,
        "rubric_per_criterion": rubric_per_criterion,
        "recall": a["recall"], "total": a["total"], "misbehave": a["misbehave"],
        "passed_tests": a["passed_tests"],
        "weights": weights,
        "detail": a,
        "grader": "pytest+rubric(trajectory)",
    }
    if verbose:
        print(f"[pytest+rubric] A={a['pytest_score']} (recall {a['recall']}/{a['total']}, "
              f"guards {a['misbehave']}) B={rubric_score} -> passed={bool(passed)}")
    return result


def write_verifier(out_dir, result: dict) -> str:
    """Write the pytest+rubric result into <out_dir>/verifier/{reward,ctrf,detail}.json.

    Same folder + shapes the snapshot test_state.py verifier produced, so any
    tooling that reads `verifier/` keeps working -- but sourced from the
    trajectory Pytest+Rubric grader instead of a world-state snapshot.
    """
    import os
    from datetime import datetime, timezone

    vdir = os.path.join(str(out_dir), "verifier")
    os.makedirs(vdir, exist_ok=True)

    weights = result.get("weights") or {}
    passed_tests = result.get("passed_tests") or {}
    total = result.get("total", 0)
    recall = result.get("recall", 0)
    misbehave = result.get("misbehave", 0)

    # CTRF: one record per pytest test. A guard (negative weight) is "passed"
    # when it did NOT trigger (the forbidden thing didn't happen).
    tests = []
    for name, w in weights.items():
        triggered = bool(passed_tests.get(name, False))
        if w >= 0:
            status = "passed" if triggered else "failed"
        else:  # guard
            status = "failed" if triggered else "passed"
        tests.append({"name": name, "status": status,
                      "extra": {"weight": w, "kind": "goal" if w >= 0 else "guard"}})
    # rubric criteria as ctrf rows too
    for c in (result.get("rubric_per_criterion") or []):
        tests.append({"name": f"rubric.{c.get('number')}",
                      "status": "passed" if c.get("satisfied") else "failed",
                      "extra": {"criterion": c.get("criterion")}})

    n_pass = sum(1 for t in tests if t["status"] == "passed")
    ctrf = {"results": {
        "tool": {"name": "complexmcp-pytest-rubric"},
        "summary": {"tests": len(tests), "passed": n_pass,
                    "failed": len(tests) - n_pass, "pending": 0, "skipped": 0,
                    "other": 0, "start": 0,
                    "stop": int(datetime.now(timezone.utc).timestamp())},
        "tests": tests,
    }}

    reward = {
        "reward": result.get("reward", 0.0),
        "completion_rate": round(recall / total, 6) if total else (1.0 if result.get("passed") else 0.0),
        "misbehaving_rate": round(misbehave / total, 6) if total else 0.0,
        "keys_required": total, "keys_reached": recall, "keys_damaged": misbehave,
        "pytest_score": result.get("pytest_score"),
        "rubric_score": result.get("rubric_score"),
        "grader": result.get("grader"),
    }

    _w(os.path.join(vdir, "reward.json"), reward)
    _w(os.path.join(vdir, "reward.txt"), None, text=str(reward["reward"]))
    _w(os.path.join(vdir, "ctrf.json"), ctrf)
    _w(os.path.join(vdir, "detail.json"), {
        "pytest": result.get("detail"),
        "rubric": result.get("rubric_per_criterion"),
        "grader": result.get("grader"),
    })
    return vdir


def _w(path, obj, text=None):
    with open(path, "w") as fh:
        fh.write(text if text is not None else json.dumps(obj, indent=2, default=str))


def _oracle_trajectory_from_plan(task_dir):
    """Load the oracle's canonical tool calls (solution/trajectory.json) into the
    trajectory shape the pytest tests read. A plan carries no responses, so we
    inject status:ok -- enough for tests that assert on calls + arguments (the
    admissibility-relevant surface). Returns None if no plan is shipped."""
    import os
    p = os.path.join(str(task_dir), "solution", "trajectory.json")
    if not os.path.exists(p):
        return None
    try:
        plan = json.load(open(p))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(plan, dict) and "steps" in plan:   # already full shape
        return plan
    steps = []
    for i, s in enumerate(plan if isinstance(plan, list) else [], 1):
        steps.append({"step": i, "reasoning": "", "tool": s.get("tool"),
                      "arguments": s.get("args", s.get("arguments", {})),
                      "response": s.get("response", {"status": "ok"})})
    return {"steps": steps, "final_message": ""}


def check_world_anchors(trajectory: dict, grading_dir: str) -> dict:
    """World-consistency gate: verify the kit's world-anchors are present in the
    agent's actual run.

    A grading kit is authored against one specific world (e.g. the seed=114514
    mcp-stump sandbox) and its ground truth hardcodes world-specific values --
    account-holder uids, entity ids, tickers. If the agent is run against a
    DIFFERENT world (e.g. the seedless seed=42 Light apps), those values don't
    exist, so the numeric reward is meaningless -- a false 0.0, not a real fail.
    This flags that so the caller can mark the run INVALID (world_mismatch)
    instead of trusting the score.

    tests/world_anchors.json holds the literal anchors the kit's world guarantees:
        {"anchors": ["user_FiBXJH9uAk5v8tFppnBp6z", "PYPL"], "world": "seed=114514"}
    (a bare list is also accepted). Each anchor MUST appear somewhere in the
    agent's trajectory (tool args / observations / final message). No file =>
    gate not applicable (backward compatible; nothing changes).
    """
    path = os.path.join(grading_dir, "world_anchors.json")
    if not os.path.exists(path):
        return {"applicable": False, "consistent": True, "missing": [], "world": None}
    spec = json.load(open(path, encoding="utf-8"))
    anchors = (spec.get("anchors") if isinstance(spec, dict) else spec) or []
    anchors = [str(a) for a in anchors]
    blob = json.dumps(trajectory or {}, default=str, ensure_ascii=False).lower()
    missing = [a for a in anchors if a.lower() not in blob]
    return {
        "applicable": True,
        "consistent": not missing,
        "missing": missing,
        "anchors": anchors,
        "world": (spec.get("world") if isinstance(spec, dict) else None),
    }


def run_controls(grading_dir, task_dir=None) -> dict:
    """Admissibility controls, graded by the SAME (pytest) grader as a real run.

      nop     empty trajectory  -> reward MUST be 0.0  (tests are non-trivial)
      oracle  solution/trajectory.json -> reward SHOULD be 1.0 (tests satisfiable)

    A task is admissible iff nop == 0.0 AND (oracle is unavailable OR oracle == 1.0).
    Runs with no rubric (deterministic Channel A only) and needs no sandbox/model.
    """
    nop = judge_trajectory_pytest({"steps": [], "final_message": ""}, grading_dir)
    out = {"nop_reward": nop["reward"], "nop_pytest": nop["pytest_score"]}

    oracle_traj = _oracle_trajectory_from_plan(task_dir) if task_dir else None
    if oracle_traj is not None:
        orc = judge_trajectory_pytest(oracle_traj, grading_dir,
                                      final_message=oracle_traj.get("final_message"))
        out["oracle_reward"] = orc["reward"]
        out["oracle_pytest"] = orc["pytest_score"]
    else:
        out["oracle_reward"] = None

    out["admissible"] = (out["nop_reward"] == 0.0
                         and out["oracle_reward"] in (None, 1.0))
    return out
