#!/usr/bin/env python3
"""
Rubric + Pytest grader 

  Channel A — deterministic pytest against the WORLD STATE. In the benchmark the agent
              runs in-process, so `old_env` / `new_env` are already full world-state dicts
              (result["old_apps"] / result["apps"]). We write them to temp files and run the
              task's tests/test_outputs.py, which reads new state via $NEW_ENV and baseline
              via $OLD_ENV. Each test maps to a weight in test_weights.json:
                 A = max(0, (Σ passed-positive-w − Σ |triggered-negative-w|) / Σ all-positive-w)

  Channel B — LLM-judged rubric against the agent's deliverable (result["output"]). Optional:
              pass a `rubric_judge(criteria, output) -> {number: bool}` callable
              (make_openai_rubric_judge() builds one from OPENAI_API_KEY/OPENAI_BASE_URL).
              Without it, Channel B is skipped and only Channel A drives pass/fail.

`judge_rubric_pytest` returns a dict shaped to drop into run_benchmark.py: it carries
`reward` / `passed` plus `recall` / `total` / `misbehave` (so the existing completion &
misbehave-rate aggregates keep working) and `pytest_score` / `rubric_score` for reporting.
Here `total` = number of positive tests, `recall` = positives passed, `misbehave` = negative
tests that triggered.
"""
import json
import os
import tempfile


def _run_pytest(test_file, weights, old_path, new_path):
    import pytest

    passed = {}

    class _Collector:
        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                passed[report.nodeid.split("::")[-1]] = report.passed

    prev = {k: os.environ.get(k) for k in ("OLD_ENV", "NEW_ENV")}
    os.environ["OLD_ENV"] = old_path
    os.environ["NEW_ENV"] = new_path
    try:
        pytest.main([test_file, "-q", "-p", "no:cacheprovider",
                     "--import-mode=importlib"], plugins=[_Collector()])
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    pos_total = sum(w for w in weights.values() if w > 0)
    earned = penalty = 0.0
    recall = total = misbehave = 0
    for name, w in weights.items():
        if w > 0:
            total += 1
        ok = passed.get(name, False)
        if not ok:
            continue
        if w > 0:
            earned += w
            recall += 1
        else:
            penalty += abs(w)
            misbehave += 1
    score = max(0.0, (earned - penalty) / pos_total) if pos_total else 0.0
    return {
        "pytest_score": round(score, 4),
        "recall": recall, "total": total, "misbehave": misbehave,
        "passed_tests": passed,
        "earned": earned, "penalty": penalty, "positive_total": pos_total,
    }


def _score_rubric(criteria, verdicts):
    pos_total = sum(c["score"] for c in criteria if c["score"] > 0)
    met = penalty = 0.0
    for c in criteria:
        v = verdicts.get(c["number"])
        if v is None or not v:
            continue
        if c["score"] > 0:
            met += c["score"]
        else:
            penalty += abs(c["score"])
    return round(max(0.0, (met - penalty) / pos_total), 4) if pos_total else 0.0


def make_openai_rubric_judge(model=None):
    """Build a rubric judge from OPENAI_API_KEY / OPENAI_BASE_URL (same creds the agent uses).
    Returns None if creds are absent so the caller degrades to Channel A only."""
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("OPENAI_BASE_URL"):
        return None
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.environ["OPENAI_BASE_URL"])
    judge_model = model or os.environ.get("RUBRIC_JUDGE_MODEL", "gpt-4o-mini")

    def judge(criteria, output):
        verdicts = {}
        for c in criteria:
            prompt = (
                "You are grading one rubric criterion against an AI agent's final message.\n"
                "Answer with exactly one word: YES or NO.\n"
                "Answer YES iff the statement in the criterion is literally true of the message.\n\n"
                f"CRITERION: {c['criterion']}\n\n"
                f"AGENT MESSAGE:\n{output}\n\nAnswer (YES/NO):"
            )
            try:
                resp = client.chat.completions.create(
                    model=judge_model,
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=4,
                )
                ans = (resp.choices[0].message.content or "").strip().upper()
                verdicts[c["number"]] = ans.startswith("Y")
            except Exception:
                verdicts[c["number"]] = None
        return verdicts

    return judge


def judge_rubric_pytest(old_env, new_env, output, grading_dir,
                        rubric_judge=None, a_threshold=1.0, b_threshold=0.7, verbose=False):
    """Grade one episode. `grading_dir` holds test_outputs.py + test_weights.json (+ rubric.json)."""
    test_file = os.path.join(grading_dir, "test_outputs.py")
    weights = json.load(open(os.path.join(grading_dir, "test_weights.json"), encoding="utf-8"))

    with tempfile.TemporaryDirectory() as tmp:
        old_path = os.path.join(tmp, "old_env.json")
        new_path = os.path.join(tmp, "new_env.json")
        json.dump(old_env, open(old_path, "w"))
        json.dump(new_env, open(new_path, "w"))
        a = _run_pytest(test_file, weights, old_path, new_path)

    rubric_score = None
    rubric_per_criterion = None
    rubric_path = os.path.join(grading_dir, "rubric.json")
    if rubric_judge is not None and os.path.exists(rubric_path):
        rubric = json.load(open(rubric_path, encoding="utf-8"))
        criteria = rubric.get("criteria", rubric) if isinstance(rubric, dict) else rubric
        verdicts = rubric_judge(criteria, output or "")
        rubric_score = _score_rubric(criteria, verdicts)
        rubric_per_criterion = [{
            "number": c.get("number"),
            "criterion": c.get("criterion"),
            "is_positive": c.get("is_positive", True),
            "score": c.get("score"),
            "satisfied": bool(verdicts.get(c.get("number"))),
        } for c in criteria]

    passed = int(a["pytest_score"] >= a_threshold and (rubric_score is None or rubric_score >= b_threshold))
    result = {
        "reward": a["pytest_score"],
        "passed": bool(passed),
        "pytest_score": a["pytest_score"],
        "rubric_score": rubric_score,
        "rubric_per_criterion": rubric_per_criterion,
        "recall": a["recall"], "total": a["total"], "misbehave": a["misbehave"],
        "detail": a,
    }
    if verbose:
        print(f"[rubric+pytest] A={a['pytest_score']} (recall {a['recall']}/{a['total']}, "
              f"misbehave {a['misbehave']}) B={rubric_score} -> passed={bool(passed)}")
    return result
