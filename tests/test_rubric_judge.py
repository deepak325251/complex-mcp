import json

from benchmark.rubric_judge import (
    evaluate_rubric,
    find_rubric_for_task,
    load_rubric,
)


def _traj(*tools_with_args):
    steps = []
    for i, (tool, args) in enumerate(tools_with_args, 1):
        steps.append({"step": i, "tool": tool, "arguments": args, "response": None})
    return {"steps": steps, "final_message": ""}


def test_tool_called_pass():
    rubric = {"checks": [
        {"check_id": "c1", "weight": 1.0,
         "check_type": "tool_called", "tool_name": "like_moment"},
    ]}
    result = evaluate_rubric(rubric, _traj(("like_moment", {})))
    assert result["rubric_score"] == 1.0
    assert result["per_check"][0]["passed"] is True


def test_tool_called_fail_wrong_name():
    rubric = {"checks": [
        {"check_id": "c1", "weight": 1.0,
         "check_type": "tool_called", "tool_name": "like_moment"},
    ]}
    result = evaluate_rubric(rubric, _traj(("search_products", {})))
    assert result["rubric_score"] == 0.0
    assert result["per_check"][0]["passed"] is False


def test_tool_called_min_calls():
    rubric = {"checks": [
        {"check_id": "c1", "weight": 1.0,
         "check_type": "tool_called", "tool_name": "add_to_cart", "min_calls": 2},
    ]}
    result_one = evaluate_rubric(rubric, _traj(("add_to_cart", {})))
    result_two = evaluate_rubric(
        rubric, _traj(("add_to_cart", {}), ("add_to_cart", {}))
    )
    assert result_one["rubric_score"] == 0.0
    assert result_two["rubric_score"] == 1.0


def test_tool_called_args_include():
    rubric = {"checks": [
        {"check_id": "c1", "weight": 1.0,
         "check_type": "tool_called", "tool_name": "like_moment",
         "args_include": {"uid": "u123"}},
    ]}
    match = evaluate_rubric(rubric, _traj(("like_moment", {"uid": "u123", "extra": 1})))
    miss = evaluate_rubric(rubric, _traj(("like_moment", {"uid": "other"})))
    assert match["rubric_score"] == 1.0
    assert miss["rubric_score"] == 0.0


def test_state_predicate_misbehave_leq():
    rubric = {"checks": [
        {"check_id": "c1", "weight": 1.0,
         "check_type": "state_predicate", "predicate": "misbehave_leq", "value": 0},
    ]}
    good = evaluate_rubric(rubric, _traj(), score={"misbehave": 0})
    bad = evaluate_rubric(rubric, _traj(), score={"misbehave": 3})
    assert good["rubric_score"] == 1.0
    assert bad["rubric_score"] == 0.0


def test_state_predicate_recall_geq():
    rubric = {"checks": [
        {"check_id": "c1", "weight": 1.0,
         "check_type": "state_predicate", "predicate": "recall_geq", "value": 2},
    ]}
    result = evaluate_rubric(rubric, _traj(), score={"recall": 3})
    assert result["rubric_score"] == 1.0


def test_state_predicate_passed_true():
    rubric = {"checks": [
        {"check_id": "c1", "weight": 1.0,
         "check_type": "state_predicate", "predicate": "passed_true"},
    ]}
    assert evaluate_rubric(rubric, _traj(), score={"passed": True})["rubric_score"] == 1.0
    assert evaluate_rubric(rubric, _traj(), score={"passed": False})["rubric_score"] == 0.0


def test_weight_normalization():
    rubric = {"checks": [
        {"check_id": "a", "weight": 2.0, "check_type": "tool_called", "tool_name": "x"},
        {"check_id": "b", "weight": 2.0, "check_type": "tool_called", "tool_name": "y"},
    ]}
    result = evaluate_rubric(rubric, _traj(("x", {})))
    assert result["rubric_score"] == 0.5


def test_partial_score_multiple_checks():
    rubric = {"checks": [
        {"check_id": "a", "weight": 0.4, "check_type": "tool_called", "tool_name": "x"},
        {"check_id": "b", "weight": 0.6, "check_type": "tool_called", "tool_name": "y"},
    ]}
    result = evaluate_rubric(rubric, _traj(("x", {})))
    assert result["rubric_score"] == 0.4


def test_unknown_check_type_fails_gracefully():
    rubric = {"checks": [
        {"check_id": "c1", "weight": 1.0, "check_type": "nonsense"},
    ]}
    result = evaluate_rubric(rubric, _traj())
    assert result["rubric_score"] == 0.0
    assert "unknown" in result["per_check"][0]["reason"]


def test_empty_rubric():
    result = evaluate_rubric({"checks": []}, _traj())
    assert result["rubric_score"] == 0.0


def test_load_and_find_rubric(tmp_path):
    task = tmp_path / "task-1"
    task.mkdir()
    rubric_path = task / "rubric.json"
    rubric_path.write_text(json.dumps({"checks": [
        {"check_id": "c1", "weight": 1.0, "check_type": "tool_called", "tool_name": "x"}
    ]}))
    found = find_rubric_for_task(str(task))
    assert found == rubric_path
    loaded = load_rubric(found)
    assert loaded["checks"][0]["tool_name"] == "x"
    assert find_rubric_for_task(str(tmp_path / "no-such-dir")) is None
