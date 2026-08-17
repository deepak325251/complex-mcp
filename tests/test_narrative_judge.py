"""Narrative judge: written evidence per criterion, opt-in, never fabricated.

The YES/NO judge runs at `max_completion_tokens=4` and can say nothing about
WHY. `report.json`'s `justification` field and `judge_response.txt` need prose,
so a narrative mode exists -- gated, because it costs a real reply per criterion.
With it off both stay empty rather than being invented.
"""

import json

import pytest

from benchmark.harbor_layout import render_judge_response, write_harbor_trial
from benchmark.rubric_pytest_judge import _parse_narrative
from benchmark.weighted_judge import judge_weighted


CRITERIA = [{"number": "1", "criterion": "reports the ledger figure",
             "score": 3, "is_positive": True}]


@pytest.mark.parametrize("reply,verdict", [
    ("YES. The message cites the ledger balance.", True),
    ("NO -- it quotes the drive figure instead.", False),
    ("**YES** the figure is present.", True),
    ("  no, absent.", False),
])
def test_verdict_parses_from_the_first_token(reply, verdict):
    assert _parse_narrative(reply)[0] is verdict


def test_unreadable_verdict_is_none_not_false():
    """Unreadable is not 'no'. Collapsing them marks satisfied criteria failed."""
    assert _parse_narrative("I'm not sure about this one.")[0] is None
    assert _parse_narrative("")[0] is None


def test_justification_keeps_the_full_reply():
    _, text = _parse_narrative("YES. Cites the $12,480 balance from the bill.")
    assert "12,480" in text


def _judge_with(justifications):
    def judge(criteria, output):
        return {c["number"]: True for c in criteria}
    judge.justifications = justifications
    judge.narrative = bool(justifications)
    return judge


def test_justifications_reach_the_rubric_rows(tmp_path):
    rp = tmp_path / "rubric.json"
    rp.write_text(json.dumps({"criteria": CRITERIA}))
    r = judge_weighted(trajectory={"steps": []}, gold_plan=[{"tool_name": "t"}],
                       weights={"graph_plan": {"weight": 3}, "rubric": {"weight": 0}},
                       threshold=1.0, final_message="m",
                       rubric_judge=_judge_with({"1": "YES. Cites the ledger."}),
                       rubric_path=str(rp))
    assert r["rubric_per_criterion"][0]["justification"] == "YES. Cites the ledger."


def test_yes_no_judge_leaves_justification_empty(tmp_path):
    rp = tmp_path / "rubric.json"
    rp.write_text(json.dumps({"criteria": CRITERIA}))
    r = judge_weighted(trajectory={"steps": []}, gold_plan=[{"tool_name": "t"}],
                       weights={"graph_plan": {"weight": 3}, "rubric": {"weight": 0}},
                       threshold=1.0, final_message="m",
                       rubric_judge=_judge_with({}), rubric_path=str(rp))
    assert "justification" not in r["rubric_per_criterion"][0]


def test_no_judge_response_without_prose():
    assert render_judge_response({"per_criterion": [
        {"number": "1", "criterion": "c", "justification": ""}]}) is None
    assert render_judge_response(None) is None


def test_judge_response_renders_only_criteria_with_evidence():
    text = render_judge_response({"per_criterion": [
        {"number": "1", "criterion": "reports figure", "justification": "YES. Cited."},
        {"number": "2", "criterion": "no email", "justification": ""},
    ]})
    assert "1: reports figure" in text and "YES. Cited." in text
    assert "no email" not in text


def test_file_absent_when_the_yes_no_judge_ran(tmp_path):
    jd = tmp_path / "j"
    (tmp_path / "t" / "tests").mkdir(parents=True)
    write_harbor_trial(jd, 1, record={"name": "t", "output": "", "usage": {}},
                       model="m", judge_result={"reward": 0.5, "traj_tests": {}},
                       task_dir=tmp_path / "t", grading_dir=tmp_path / "t" / "tests",
                       rubric_result={"per_criterion": [
                           {"number": "1", "criterion": "c", "satisfied": True}]},
                       job_id="j", job_label="l")
    assert not (jd / "trajectory/Run 1/judge_response.txt").exists()


def test_file_written_when_evidence_exists(tmp_path):
    jd = tmp_path / "j"
    (tmp_path / "t" / "tests").mkdir(parents=True)
    write_harbor_trial(jd, 1, record={"name": "t", "output": "", "usage": {}},
                       model="m", judge_result={"reward": 0.5, "traj_tests": {}},
                       task_dir=tmp_path / "t", grading_dir=tmp_path / "t" / "tests",
                       rubric_result={"per_criterion": [
                           {"number": "1", "criterion": "c", "satisfied": True,
                            "justification": "YES. Because X."}]},
                       job_id="j", job_label="l")
    p = jd / "trajectory/Run 1/judge_response.txt"
    assert p.is_file() and "YES. Because X." in p.read_text()
