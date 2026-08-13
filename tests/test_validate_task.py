"""Prevention gate: catch fictional tool names, wrong-world GT, orphan traj keys."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from benchmark.validate_task import registered_tools, check_gold_plan, check_traj_tests, validate


def test_registered_tools_are_real():
    t = registered_tools("LightJira")
    assert "list_sprints" in t and "search" in t
    assert "get_sprint" not in t          # the fictional name we had to remove


def _mk(tmp, gold=None, weights=None, tests_py=None):
    d = tmp / "tests"; d.mkdir(parents=True, exist_ok=True)
    if gold is not None:
        (d / "gold_plan.json").write_text(json.dumps(gold))
    if weights is not None:
        (d / "test_weights.json").write_text(json.dumps(weights))
    if tests_py is not None:
        (d / "test_outputs.py").write_text(tests_py)
    return str(tmp)


def test_gold_plan_flags_fictional_tool(tmp_path):
    task = _mk(tmp_path, gold=[[{"server_name": "LightJira", "tool_name": "get_sprint"}]])
    probs = check_gold_plan(task)
    assert any("not a published tool" in p for p in probs)


def test_gold_plan_accepts_real_tool(tmp_path):
    task = _mk(tmp_path, gold=[[{"server_name": "LightJira", "tool_name": "list_sprints"}]])
    assert check_gold_plan(task) == []


def test_traj_key_without_function_flagged(tmp_path):
    task = _mk(tmp_path,
               weights={"components": {"traj_tests": {"tests": {"test_ghost": 3}}}},
               tests_py="def test_real():\n    assert True\n")
    probs = check_traj_tests(task)
    assert any("test_ghost" in p for p in probs)


def test_fixed_task_passes_gate():
    task = "bundle/input/02-auth-v2-rollout-coordination"
    if os.path.isdir(task):
        assert validate(task)["ok"], validate(task)["problems"]
