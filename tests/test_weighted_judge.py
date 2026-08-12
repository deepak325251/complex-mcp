"""Unit tests for the hybrid weighted grader (benchmark/weighted_judge.py)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.weighted_judge import judge_weighted, load_weights, _score_rubric


# A tiny world: one mutable field the task should change, one it must not touch.
OLD = {"cart": {"item": "none"}, "balance": 100}
GT = {"cart": {"item": "sony"}, "balance": 100}

GOLD = [[{"tool_name": "search_items"}], [{"tool_name": "add_to_cart", "dependencies": [0]}]]
GOOD_TRAJ = {"steps": [{"tool": "LightShop::search_items"}, {"tool": "LightShop::add_to_cart"}],
             "final_message": "done"}
BAD_TRAJ = {"steps": [{"tool": "LightShop::add_to_cart"}], "final_message": "oops"}


def test_full_solve_scores_one():
    new = {"cart": {"item": "sony"}, "balance": 100}   # correct, nothing else touched
    r = judge_weighted(old_env=OLD, new_env=new, gt_env=GT,
                       trajectory=GOOD_TRAJ, gold_plan=GOLD)
    assert r["reward"] == 1.0
    assert r["passed"] is True
    assert r["quadrant"] == "SOLVED"
    assert r["state"]["Rc"] == 1.0 and r["state"]["Rb"] == 0.0
    assert r["plan"]["graph_f1"] == 1.0


def test_misbehave_penalizes():
    # correct target, but it also damaged balance -> Rb > 0, penalty applies.
    new = {"cart": {"item": "sony"}, "balance": 50}
    r = judge_weighted(old_env=OLD, new_env=new, gt_env=GT,
                       trajectory=GOOD_TRAJ, gold_plan=GOLD)
    assert r["state"]["misbehave"] == 1
    assert r["penalty"] > 0
    assert r["reward"] < 1.0            # penalty pulled it below a clean solve
    assert r["passed"] is False
    assert "state_misbehave" in r["components"]


def test_brute_force_quadrant():
    # right end state, wrong plan (missing a required node).
    new = {"cart": {"item": "sony"}, "balance": 100}
    r = judge_weighted(old_env=OLD, new_env=new, gt_env=GT,
                       trajectory=BAD_TRAJ, gold_plan=GOLD)
    assert r["quadrant"] == "BRUTE_FORCE"
    assert r["plan"]["graph_f1"] < 1.0


def test_execution_fail_quadrant():
    # right plan, wrong end state.
    new = {"cart": {"item": "none"}, "balance": 100}   # never actually bought
    r = judge_weighted(old_env=OLD, new_env=new, gt_env=GT,
                       trajectory=GOOD_TRAJ, gold_plan=GOLD)
    assert r["quadrant"] == "EXECUTION_FAIL"


def test_degradation_no_gt_renormalizes():
    # gt_env unavailable -> state components drop, score is plan-only.
    r = judge_weighted(old_env=None, new_env=None, gt_env=None,
                       trajectory=GOOD_TRAJ, gold_plan=GOLD)
    assert r["state"] == {"status": "unavailable"}
    assert r["quadrant"] == "PLAN_ONLY"
    assert "state_completion" not in r["components"]
    assert r["pos_total"] == 3          # only graph_plan's weight remains
    assert r["reward"] == 1.0           # perfect plan, renormalized


def test_penalty_capped_at_weight():
    # Rb severity is capped at 1.0 and each penalty is capped at |weight|,
    # so max(0,...) floors reward but can't go negative.
    new = {"cart": {"item": "wrong"}, "balance": 1}    # incomplete AND damaging
    r = judge_weighted(old_env=OLD, new_env=new, gt_env=GT,
                       trajectory=BAD_TRAJ, gold_plan=GOLD)
    assert r["reward"] >= 0.0
    assert r["penalty"] <= 4            # capped at |state_misbehave weight|


def test_custom_weights_from_config(tmp_path):
    (tmp_path / "test_weights.json").write_text(
        '{"threshold": 0.5, "components": {"graph_plan": {"weight": 10}, '
        '"state_completion": {"weight": 1}, "state_misbehave": {"weight": -1}}}')
    thr, comps = load_weights(str(tmp_path))
    assert thr == 0.5
    assert comps["graph_plan"]["weight"] == 10
    r = judge_weighted(old_env=OLD, new_env={"cart": {"item": "sony"}, "balance": 100},
                       gt_env=GT, trajectory=GOOD_TRAJ, gold_plan=GOLD,
                       grading_dir=str(tmp_path))
    assert r["threshold"] == 0.5
    assert r["components"]["graph_plan"]["weight"] == 10


def test_rubric_scoring():
    crit = [{"number": "R1", "score": 5}, {"number": "R2", "score": -3}]
    score, per = _score_rubric(crit, {"R1": True, "R2": False})
    assert score == 1.0
    score2, _ = _score_rubric(crit, {"R1": True, "R2": True})   # hallucination fires
    assert score2 < 1.0
