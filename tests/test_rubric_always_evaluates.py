"""A rubric at weight 0 must still be EVALUATED -- just not scored.

`rubric` weight 0 is a task saying "keep this out of the reward", not "never
run it". Gating evaluation on the weight left every such task with
`rubric_score: null` and an empty rubric block forever -- so the QC/reporting
channel was dark on exactly the tasks that had deliberately excluded it from
the reward, and the delivered report.json could never carry a rubric.

The contract these tests pin:
  weight 0  -> rubric_score + rubric_per_criterion populated,
               `rubric` absent from components/basis, reward UNCHANGED.
  weight >0 -> all of the above AND `rubric` contributes to the ledger.
"""

import json

import pytest

from benchmark.weighted_judge import judge_weighted


CRITERIA = [
    {"number": "1", "criterion": "reports the ledger figure", "score": 3,
     "is_positive": True},
    {"number": "2", "criterion": "names the drive number unverified", "score": 2,
     "is_positive": True},
    {"number": "3", "criterion": "emailed the funder", "score": 4,
     "is_positive": False},
]

GOLD = [{"tool_name": "list_messages"}, {"tool_name": "post_message"}]
TRAJ = {"steps": [{"tool": "list_messages"}, {"tool": "post_message"}],
        "final_message": "done"}


@pytest.fixture
def rubric_path(tmp_path):
    p = tmp_path / "rubric.json"
    p.write_text(json.dumps({"criteria": CRITERIA}))
    return str(p)


def _judge(criteria, output):
    """Satisfies both positive criteria, does not trip the guard -> 5/5."""
    return {"1": True, "2": True, "3": False}


def _run(weights, rubric_path, judge=_judge):
    return judge_weighted(
        trajectory=TRAJ, gold_plan=GOLD, weights=weights, threshold=1.0,
        final_message="done", rubric_judge=judge, rubric_path=rubric_path)


W_ZERO = {"graph_plan": {"weight": 3}, "rubric": {"weight": 0}}
W_SCORED = {"graph_plan": {"weight": 3}, "rubric": {"weight": 2}}


def test_weight_zero_still_evaluates(rubric_path):
    r = _run(W_ZERO, rubric_path)
    assert r["rubric_score"] == 1.0
    assert len(r["rubric_per_criterion"]) == 3


def test_weight_zero_stays_out_of_the_ledger(rubric_path):
    r = _run(W_ZERO, rubric_path)
    assert "rubric" not in r["components"]
    assert "rubric" not in r["basis"]
    assert "rubric" not in r["grader"]


def test_weight_zero_does_not_move_the_reward(rubric_path):
    """The whole safety property: turning evaluation on must not change scoring."""
    with_rubric = _run(W_ZERO, rubric_path)["reward"]
    without = judge_weighted(trajectory=TRAJ, gold_plan=GOLD, weights=W_ZERO,
                             threshold=1.0, rubric_judge=None,
                             rubric_path=None)["reward"]
    assert with_rubric == without


def test_a_failing_rubric_at_weight_zero_still_does_not_move_the_reward(rubric_path):
    r_good = _run(W_ZERO, rubric_path)
    r_bad = _run(W_ZERO, rubric_path,
                 judge=lambda c, o: {"1": False, "2": False, "3": True})
    # Nothing positive earned, guard "3" fired -> score goes negative, derived
    # straight from CRITERIA rather than a hardcoded number.
    pos_total = sum(c["score"] for c in CRITERIA if c["is_positive"])
    penalty = sum(c["score"] for c in CRITERIA if not c["is_positive"])
    assert r_bad["rubric_score"] == pytest.approx(-penalty / pos_total)
    assert r_bad["reward"] == r_good["reward"]   # reward untouched


def test_nonzero_weight_does_contribute(rubric_path):
    r = _run(W_SCORED, rubric_path)
    assert r["components"]["rubric"] == {"weight": 2, "value": 1.0, "earned": 2.0}
    assert "rubric" in r["basis"]


def test_no_judge_leaves_channel_null(rubric_path):
    r = _run(W_ZERO, rubric_path, judge=None)
    assert r["rubric_score"] is None
    assert r["rubric_per_criterion"] is None


def test_missing_rubric_file_leaves_channel_null(tmp_path):
    r = _run(W_ZERO, str(tmp_path / "absent.json"))
    assert r["rubric_score"] is None


def test_guard_polarity_preserved_at_weight_zero(rubric_path):
    """is_positive:false with a POSITIVE score is a guard: satisfied=True means
    the violation fired. Weight 0 must not change that reading."""
    r = _run(W_ZERO, rubric_path,
             judge=lambda c, o: {"1": True, "2": True, "3": True})
    per = {c["number"]: c for c in r["rubric_per_criterion"]}
    assert per["3"]["is_positive"] is False
    assert per["3"]["satisfied"] is True
    assert r["rubric_score"] == 0.2      # (5 - 4) / 5
