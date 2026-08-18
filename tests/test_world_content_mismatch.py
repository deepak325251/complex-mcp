"""Reporting fixes: rate clamping, environment class, rubric fields and polarity.

World-mismatch detection itself lives upstream in `_content_mismatch`;

`_world_mismatch` only asks whether entity IDs are disjoint. These fixtures mint
sequential synthetic ids (`AAMkAGmsg0000001`), so two unrelated worlds collide on
every id while every field differs — the bake holds
`nathaniel.kessel@shpa-savannah.org` and the live world `priya.nair@contoso.com`
under the SAME message id. Content has to be compared, not just identity.
"""

import pytest

from benchmark.weighted_judge import _content_mismatch, state_admissibility


def env(**apps):
    return {a: {"status": "ok", "output": {"messages": recs}}
            for a, recs in apps.items()}


SHPA = [{"id": f"m{i}", "from_address": f"user{i}@shpa-savannah.org",
         "subject": f"delivery window {i}", "from_name": "Logistics"}
        for i in range(4)]
CONTOSO = [{"id": f"m{i}", "from_address": f"other{i}@contoso.com",
            "subject": f"invoice INV-{i}", "from_name": "Billing"}
           for i in range(4)]










# --- B5/B6/B7/B8 ------------------------------------------------------------

def test_misbehaving_rate_is_clamped():
    """Reported 12.39 (1239%) — the component clamped, the summary did not."""
    from scripts.task_writer import write_mcp_stump_run
    import json as _json, tempfile
    from pathlib import Path
    rec = {"name": "t/x", "output": "", "query": "q", "valid_tool_calls": 1,
           "invalid_tool_calls": 0, "error_tool_calls": 0, "tool_cnt": {},
           "seed": 1, "tokens": {}, "usage": {}, "old_env": {}, "new_env": {},
           "termination_reason": "end_tag"}
    score = {"gradeable": True, "reward": 0.0, "recall": 0, "total": 6,
             "misbehave": 58, "passed": False}       # 58/6 = 9.67 unclamped
    with tempfile.TemporaryDirectory() as td:
        run_dir, _ = write_mcp_stump_run(Path(td), rec, model="m", score=dict(score))
        rep = _json.loads((run_dir / "report.json").read_text())
    assert rep["misbehaving_rate"] == 1.0


def test_inadmissible_state_is_classified_as_environment_not_model():
    from benchmark.classify_failure import classify
    v = classify(trajectory={"steps": [{"tool": "x"}]},
                 tool_summary={"valid_tool_calls": 1, "invalid_tool_calls": 0,
                               "error_tool_calls": 0},
                 score={"passed": False, "state_admissible": False,
                        "state_reason": "empty_dump:LightX", "recall": 0,
                        "total": 7, "misbehave": 75, "misbehave_kind": "state_guard"},
                 task_context={}, final_message="done")
    assert v.failure_class.value == "environment_mismatch"
    assert v.category == "programmatic"          # not a model-behaviour bucket


def test_admissible_run_is_still_classified_on_behaviour():
    """The early return must not swallow genuine model failures."""
    from benchmark.classify_failure import classify
    v = classify(trajectory={"steps": [{"tool": "x"}]},
                 tool_summary={"valid_tool_calls": 1, "invalid_tool_calls": 0,
                               "error_tool_calls": 0},
                 score={"passed": False, "state_admissible": True, "recall": 1,
                        "total": 4, "misbehave": 0, "misbehave_kind": "state_guard"},
                 task_context={}, final_message="done")
    assert v.failure_class.value != "environment_mismatch"


def test_rubric_rows_carry_type_and_importance():
    """A criterion authored "critical" was delivered as "important"."""
    from benchmark.weighted_judge import _score_rubric
    crit = [{"number": "1", "criterion": "c", "score": 3, "is_positive": True,
             "type": "constraint_compliance", "evaluation_target": "final_answer",
             "importance": "critical"}]
    _, per = _score_rubric(crit, {"1": True})
    assert per[0]["type"] == "constraint_compliance"
    assert per[0]["importance"] == "critical"


def test_rubric_guard_polarity_matches_the_pytest_block():
    """passed=True on a guard meant the violation FIRED — inverse of
    pytest.tests[] in the same report.json."""
    from benchmark.harbor_layout import build_report
    rub = {"per_criterion": [
        {"number": "1", "criterion": "good thing", "score": 3,
         "is_positive": True, "satisfied": True},
        {"number": "2", "criterion": "forbidden thing", "score": 5,
         "is_positive": False, "satisfied": True},    # violation FIRED
        {"number": "3", "criterion": "other forbidden", "score": 5,
         "is_positive": False, "satisfied": False},   # stayed clean
    ]}
    rows = {r["number"]: r for r in build_report("m", 1, {}, None, rub)["rubric"]}
    assert rows["1"]["passed"] is True      # positive satisfied -> good
    assert rows["2"]["passed"] is False     # guard fired -> NOT passed
    assert rows["3"]["passed"] is True      # guard held -> passed






def test_upstream_content_detector_catches_same_id_different_content():
    """Kept as a guard on the behaviour we depend on: `_content_mismatch` is what
    makes an inadmissible world visible, and B6 routes off it."""
    assert _content_mismatch(env(A=CONTOSO), env(A=SHPA)) is True
    assert _content_mismatch(env(A=SHPA), env(A=SHPA)) is False


def test_admissibility_flags_a_substituted_world():
    ok, reason = state_admissibility(env(A=SHPA), env(A=CONTOSO), env(A=SHPA))
    assert ok is False and reason == "content_mismatch"
