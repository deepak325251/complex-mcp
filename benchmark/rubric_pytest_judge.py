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
import sys
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
    """`None` in ``verdicts`` means the grader call failed for that criterion
    (see make_openai_rubric_judge/make_anthropic_rubric_judge below) -- it is
    "not evaluated", not "evaluated and found lacking". If every criterion
    failed to grade, the denominator would still be the full rubric weight
    while nothing was ever actually checked, silently reporting a confident
    0.0 for a run that was never judged. Report None (not evaluated) instead,
    same "absent means null, not zero" contract as runreport.py."""
    pos_total = sum(c["score"] for c in criteria if c["score"] > 0)
    met = penalty = 0.0
    n_graded = 0
    for c in criteria:
        v = verdicts.get(c["number"])
        if v is None:
            continue
        n_graded += 1
        if not v:
            continue
        if c["score"] > 0:
            met += c["score"]
        else:
            penalty += abs(c["score"])
    if criteria and n_graded == 0:
        print(
            f"[rubric] WARNING: all {len(criteria)} rubric criteria failed to "
            "grade -- reporting rubric_score as None, not 0.0.",
            file=sys.stderr,
        )
        return None
    return (met - penalty) / pos_total if pos_total else 0.0


def _parse_narrative(text: str):
    """`(verdict, justification)` from a narrative judge reply.

    Expected first token is YES/NO, with the reasoning after it. A reply whose
    verdict cannot be read returns `(None, ...)` -- unreadable is NOT "no", and
    collapsing the two silently marks satisfied criteria as failed.
    """
    body = (text or "").strip()
    head = body.lstrip("*# ").upper()
    if head.startswith("YES"):
        return True, body
    if head.startswith("NO"):
        return False, body
    return None, body


def make_openai_rubric_judge(model=None, narrative: bool | None = None):
    """Build a rubric judge from OPENAI_API_KEY / OPENAI_BASE_URL (same creds the agent uses).
    Returns None if creds are absent so the caller degrades to Channel A only.

    With `narrative` (env `RUBRIC_JUDGE_NARRATIVE=1`) the judge also returns a
    written justification per criterion, which is what fills
    `report.json` `rubric[].justification` and `judge_response.txt`. It costs
    more tokens per criterion, so it is opt-in; with it off those fields stay
    empty rather than being invented.

    The returned callable exposes the justifications on `judge.justifications`
    (a `{number: text}` dict) so the verdict contract -- `{number: bool}` --
    is unchanged for every existing caller.
    """
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("OPENAI_BASE_URL"):
        return None
    from openai import OpenAI

    if narrative is None:
        narrative = os.environ.get("RUBRIC_JUDGE_NARRATIVE", "") == "1"

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.environ["OPENAI_BASE_URL"])
    judge_model = model or os.environ.get("RUBRIC_JUDGE_MODEL", "gpt-4o-mini")

    def judge(criteria, output):
        verdicts = {}
        judge.justifications = {}
        for c in criteria:
            if narrative:
                prompt = (
                    "You are grading one rubric criterion against an AI agent's final message.\n"
                    "Begin your reply with exactly YES or NO, then one or two sentences\n"
                    "citing the specific evidence for that verdict.\n"
                    "Answer YES iff the statement in the criterion is literally true of the message.\n\n"
                    f"CRITERION: {c['criterion']}\n\n"
                    f"AGENT MESSAGE:\n{output}\n\nAnswer:"
                )
            else:
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
                    max_completion_tokens=300 if narrative else 4,
                )
                raw = resp.choices[0].message.content or ""
                if narrative:
                    verdict, text = _parse_narrative(raw)
                    verdicts[c["number"]] = verdict
                    judge.justifications[c["number"]] = text
                else:
                    verdicts[c["number"]] = raw.strip().upper().startswith("Y")
            except Exception as exc:
                verdicts[c["number"]] = None
                if not getattr(judge, "_warned", False):
                    judge._warned = True
                    print(f"[rubric] OpenAI rubric judge call failed ({type(exc).__name__}: "
                          f"{exc}) against {os.environ.get('OPENAI_BASE_URL')!r} -- "
                          "criterion(s) will report as ungraded, not failed. This warning "
                          "prints once per process.", file=sys.stderr)
        return verdicts

    # Advertised on the callable so callers can read the extra output without
    # changing the verdict contract ({number: bool}) every existing caller uses.
    judge.narrative = narrative
    judge.justifications = {}
    return judge


def make_anthropic_rubric_judge(model=None):
    """Build a rubric judge from ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY -- the
    same ccbridge creds the agent uses, so no OpenAI key is needed.

    Returns None if creds are absent so the caller degrades to Channel A only.
    Uses the raw /v1/messages HTTP API via stdlib urllib (no anthropic SDK dep).
    """
    base = (os.environ.get("ANTHROPIC_BASE_URL") or os.environ.get("ANTHROPIC_API_BASE") or "").rstrip("/")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not base or not key:
        return None
    import json as _json
    import urllib.request

    judge_model = model or os.environ.get("RUBRIC_JUDGE_MODEL", "claude-opus-4-8")
    url = f"{base}/v1/messages"

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
            body = _json.dumps({
                "model": judge_model,
                "max_tokens": 8,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(url, data=body, method="POST", headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = _json.loads(resp.read().decode())
                # /v1/messages -> {"content": [{"type":"text","text":"YES"}], ...}
                parts = data.get("content") or []
                text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip().upper()
                verdicts[c["number"]] = text.startswith("Y")
            except Exception as exc:
                verdicts[c["number"]] = None
                if not getattr(judge, "_warned", False):
                    judge._warned = True
                    print(f"[rubric] Anthropic rubric judge call failed ({type(exc).__name__}: "
                          f"{exc}) against {url!r} -- criterion(s) will report as ungraded, "
                          "not failed. This warning prints once per process.", file=sys.stderr)
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
            "graded": verdicts.get(c.get("number")) is not None,
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
