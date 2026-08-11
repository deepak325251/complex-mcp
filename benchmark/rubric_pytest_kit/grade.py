#!/usr/bin/env python3
"""
ComplexMCP harbour grader — replaces the binary state-diff verifier.

Two channels, combined:

  Channel A (deterministic)  : run test_outputs.py under pytest, map each test to its
                               weight in test_weights.json, score
                                 A = max(0, (Σ passed-positive-w − Σ |triggered-neg-w|)
                                             / Σ all-positive-w)
                               A FAILED test contributes 0 regardless of sign, so a
                               crashed / no-op agent cannot dodge a penalty.

  Channel B (LLM-judged)     : rubric.json criteria graded against the agent deliverable
                               (output.md). This script does NOT call an LLM; it consumes
                               a verdicts file (rubric_verdicts.json: {"R1": true, ...})
                               produced by the rubric judge (see GENERATOR.md / test.sh),
                               scored on the same {-5,-3,-1,1,3,5} scale:
                                 B = max(0, (Σ met-positive-score − Σ |triggered-neg-score|)
                                             / Σ all-positive-score)
                               If no verdicts file is present, B is reported as null and
                               the combined reward falls back to Channel A only.

  reward = 1 iff A >= A_THRESHOLD and (B is null or B >= B_THRESHOLD)

Env / paths (all overridable):
  TESTS_PY, WEIGHTS_JSON, RUBRIC_JSON, RUBRIC_VERDICTS  (default: alongside this file)
  VERIFIER_LOG_DIR (default /logs/verifier)
  A_THRESHOLD (default 1.0)   B_THRESHOLD (default 0.7)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _p(env, name):
    return os.environ.get(env, os.path.join(HERE, name))


def run_pytest(tests_py, weights):
    import pytest

    passed = {}

    class Collector:
        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                passed[report.nodeid.split("::")[-1]] = report.passed

    pytest.main([tests_py, "-q", "-p", "no:cacheprovider", "--import-mode=importlib"],
                plugins=[Collector()])

    pos_total = sum(w for w in weights.values() if w > 0)
    earned = 0.0
    penalty = 0.0
    for name, w in weights.items():
        if not passed.get(name, False):
            continue  # failed/absent test contributes 0 (both signs)
        if w > 0:
            earned += w
        else:
            penalty += abs(w)
    score = max(0.0, (earned - penalty) / pos_total) if pos_total else 0.0
    return score, {"passed": passed, "positive_total": pos_total,
                   "earned": earned, "penalty": penalty}


def score_rubric(rubric, verdicts):
    crits = rubric.get("criteria", rubric) if isinstance(rubric, dict) else rubric
    pos_total = sum(c["score"] for c in crits if c["score"] > 0)
    met = 0.0
    penalty = 0.0
    for c in crits:
        v = verdicts.get(c["number"])
        if v is None:
            continue
        # positive criterion: v=True means desired behaviour present -> credit.
        # negative criterion (is_positive false): v=True means the bad thing was
        # detected -> penalty. Verdict is always "did the described text happen?".
        if v:
            if c["score"] > 0:
                met += c["score"]
            else:
                penalty += abs(c["score"])
    score = max(0.0, (met - penalty) / pos_total) if pos_total else 0.0
    return score, {"positive_total": pos_total, "met": met, "penalty": penalty}


def main():
    weights = json.load(open(_p("WEIGHTS_JSON", "test_weights.json"), encoding="utf-8"))
    a_score, a_detail = run_pytest(_p("TESTS_PY", "test_outputs.py"), weights)

    b_score = None
    b_detail = None
    verdicts_path = _p("RUBRIC_VERDICTS", "rubric_verdicts.json")
    rubric_path = _p("RUBRIC_JSON", "rubric.json")
    if os.path.exists(verdicts_path) and os.path.exists(rubric_path):
        rubric = json.load(open(rubric_path, encoding="utf-8"))
        verdicts = json.load(open(verdicts_path, encoding="utf-8"))
        b_score, b_detail = score_rubric(rubric, verdicts)

    a_thr = float(os.environ.get("A_THRESHOLD", "1.0"))
    b_thr = float(os.environ.get("B_THRESHOLD", "0.7"))
    reward = int(a_score >= a_thr and (b_score is None or b_score >= b_thr))

    out = {
        "reward": reward,
        "pytest_score": round(a_score, 4),
        "rubric_score": None if b_score is None else round(b_score, 4),
        "pytest_detail": a_detail,
        "rubric_detail": b_detail,
        "thresholds": {"A": a_thr, "B": b_thr},
    }

    log_dir = os.environ.get("VERIFIER_LOG_DIR", "/logs/verifier")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "reward.json"), "w") as f:
        json.dump(out, f, indent=2)
    with open(os.path.join(log_dir, "reward.txt"), "w") as f:
        f.write(str(reward))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
