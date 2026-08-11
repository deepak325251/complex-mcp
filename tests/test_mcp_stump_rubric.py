from __future__ import annotations

import json
from pathlib import Path

from benchmark.rubric_judge import (
    evaluate_rubric,
    load_rubric,
    find_rubric_for_task,
)


def _traj(*steps):
    return {"steps": list(steps), "final_message": "done"}


def _crit(number, criterion, is_positive, score=2, target="final_answer"):
    return {
        "number": number,
        "criterion": criterion,
        "is_positive": is_positive,
        "score": score,
        "evaluation_target": target,
    }


def _make_grader(answers):
    def _grader(criterion, context):
        idx = _grader.calls
        _grader.calls += 1
        return answers[idx]
    _grader.calls = 0
    return _grader


def test_format_detection_dict_vs_list(tmp_path: Path):
    dict_r = tmp_path / "d.json"
    dict_r.write_text(json.dumps({"checks": []}))
    list_r = tmp_path / "l.json"
    list_r.write_text(json.dumps([]))
    assert isinstance(load_rubric(dict_r), dict)
    assert isinstance(load_rubric(list_r), list)


def test_mcp_stump_all_positive_hit_full_score():
    rubric = [_crit(1, "did A", True, 3), _crit(2, "did B", True, 1)]
    grader = _make_grader([(True, "yes"), (True, "yes")])
    result = evaluate_rubric(rubric, _traj(), final_message="ok",
                             llm_grader=grader)
    assert result["format"] == "mcp-stump"
    assert result["rc"] == 1.0
    assert result["rb"] == 0.0
    assert result["rubric_score"] == 1.0
    assert result["rubric_passed"] is True


def test_mcp_stump_partial_positive_score():
    rubric = [_crit(1, "A", True, 3), _crit(2, "B", True, 1)]
    grader = _make_grader([(True, "yes"), (False, "no")])
    result = evaluate_rubric(rubric, _traj(), final_message="",
                             llm_grader=grader)
    assert result["rc"] == 0.75
    assert result["rb"] == 0.0
    assert result["rubric_score"] == 0.75
    assert result["rubric_passed"] is False


def test_mcp_stump_negative_criterion_hit_zeroes_score():
    rubric = [_crit(1, "did A", True, 2), _crit(2, "leaked secret", False, 3)]
    grader = _make_grader([(True, "yes"), (True, "yes")])
    result = evaluate_rubric(rubric, _traj(), final_message="",
                             llm_grader=grader)
    assert result["rc"] == 1.0
    assert result["rb"] == 1.0
    assert result["rubric_score"] == 0.0
    assert result["rubric_passed"] is False


def test_mcp_stump_no_positives_gives_rc_one():
    rubric = [_crit(1, "no-leak", False, 2)]
    grader = _make_grader([(False, "no")])
    result = evaluate_rubric(rubric, _traj(), final_message="",
                             llm_grader=grader)
    assert result["rc"] == 1.0
    assert result["rb"] == 0.0
    assert result["rubric_passed"] is True


def test_mcp_stump_rubric_passed_key_not_ambiguous_passed():
    rubric = [_crit(1, "did A", True, 2)]
    grader = _make_grader([(True, "yes")])
    result = evaluate_rubric(rubric, _traj(), final_message="ok",
                             llm_grader=grader)
    assert "rubric_passed" in result
    assert "passed" not in result


def test_mcp_stump_per_criterion_records_target(tmp_path: Path):
    rubric = [
        _crit(1, "final says X", True, 2, target="final_answer"),
        _crit(2, "called Y in traj", True, 1, target="trajectory"),
    ]
    grader = _make_grader([(True, "in msg"), (True, "in traj")])
    result = evaluate_rubric(rubric, _traj({"tool": "Y"}),
                             final_message="X", llm_grader=grader)
    per = result["per_criterion"]
    assert len(per) == 2
    assert per[0]["number"] == 1
    assert per[0]["satisfied"] is True
    assert per[1]["number"] == 2
    assert per[1]["satisfied"] is True


def test_find_rubric_for_task(tmp_path: Path):
    (tmp_path / "rubric.json").write_text("[]")
    assert find_rubric_for_task(tmp_path) is not None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert find_rubric_for_task(empty) is None
