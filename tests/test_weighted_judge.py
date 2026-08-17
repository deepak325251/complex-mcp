"""Unit tests for the hybrid weighted grader (benchmark/weighted_judge.py)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.weighted_judge import (
    judge_weighted, load_weights, _score_rubric, state_admissibility,
    _world_mismatch, _ids_by_container,
)


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


def test_empty_dump_is_inadmissible_not_zero():
    # The facade dumped nothing for the app gt_env grades (Layer-1 breakage).
    # This must be flagged inadmissible, NOT scored as Rc≈0 completion.
    gt = {"LightJira": {"output": {"issues": {"ENG-102": {"status": "Open"}}}}}
    empty = {"LightJira": {"status": "ok", "output": {}}}
    ok, reason = state_admissibility(OLD, empty, gt)
    assert ok is False and reason.startswith("empty_dump")
    r = judge_weighted(old_env=gt, new_env=empty, gt_env=gt,
                       trajectory=GOOD_TRAJ, gold_plan=GOLD)
    assert r["state_admissible"] is False
    assert r["state"]["status"] == "inadmissible"
    assert r["quadrant"] == "STATE_INADMISSIBLE"
    assert "state_completion" not in r["components"]   # never fabricated
    assert r["grader"].startswith("weighted(") and "state" not in r["grader"]


def test_wrong_world_gt_is_inadmissible():
    # gt_env references PR 218; the served dump only has PR 144 -> different world.
    gt = {"LightGithub": {"output": {"repos": {"o/a": {"pulls": {"218": {"state": "open"}}}}}}}
    served = {"LightGithub": {"output": {"repos": {"o/a": {"pulls": {"144": {"state": "open"}}}}}}}
    ok, reason = state_admissibility(gt, served, gt)
    assert ok is False and reason == "world_mismatch"


def test_guardrail_zero_required_changes_no_false_perfect():
    # gt == old everywhere: nothing SHOULD change (total==0). The old code
    # granted a false Rc=1.0; now completion is simply not graded, and an
    # untouched world is clean (no misbehave).
    r = judge_weighted(old_env=OLD, new_env=dict(OLD), gt_env=dict(OLD),
                       trajectory=GOOD_TRAJ, gold_plan=GOLD)
    assert "state_completion" not in r["components"]
    assert r["state"]["Rc"] is None
    assert r["misbehave"] == 0


def test_valid_world_still_admissible():
    ok, reason = state_admissibility(OLD, {"cart": {"item": "sony"}, "balance": 100}, GT)
    assert ok is True and reason is None


def test_rubric_scoring():
    crit = [{"number": "R1", "score": 5}, {"number": "R2", "score": -3}]
    score, per = _score_rubric(crit, {"R1": True, "R2": False})
    assert score == 1.0
    score2, _ = _score_rubric(crit, {"R1": True, "R2": True})   # hallucination fires
    assert score2 < 1.0


def test_rubric_guard_polarity_not_capped():
    # Guard criteria authored with a POSITIVE score + is_positive:false (the
    # mcp-stump convention). A clean run (guards satisfied:false) must NOT be
    # capped by them: denominator is the positive criteria only.
    crit = [
        {"number": "1", "score": 3, "is_positive": True},   # satisfied
        {"number": "2", "score": 3, "is_positive": True},   # missed
        {"number": "3", "score": 2, "is_positive": True},   # satisfied
        {"number": "4", "score": 2, "is_positive": True},   # missed
        {"number": "5", "score": 3, "is_positive": False},  # no violation
        {"number": "6", "score": 3, "is_positive": False},  # no violation
        {"number": "7", "score": 3, "is_positive": False},  # no violation
    ]
    verdicts = {"1": True, "2": False, "3": True, "4": False,
                "5": False, "6": False, "7": False}
    score, _ = _score_rubric(crit, verdicts)
    assert score == 0.5           # 5/10, NOT the old 5/19 = 0.2632

    # A clean run that satisfies every positive criterion reaches a perfect 1.0
    # (previously impossible — the guards ate the denominator).
    clean = {"1": True, "2": True, "3": True, "4": True,
             "5": False, "6": False, "7": False}
    assert _score_rubric(crit, clean)[0] == 1.0

    # A violation still subtracts: firing guard 5 pulls it below the clean score.
    dirty = dict(clean, **{"5": True})
    assert _score_rubric(crit, dirty)[0] < 1.0


# ---------------------------------------------------------------------------
# _ids_by_container / _world_mismatch: the old cross-app allowlist
# (pulls/issues/channels/repos/tickets/cards/boards/sprints/users/projects...)
# was shaped for GitHub/Jira/Slack/Trello-style apps. It had zero overlap with
# apps like Gmail (messages/drafts/labels), QuickBooks (invoices/payments/...),
# DocuSign (envelopes) or Calendar (events) — so a whole-world substitution in
# those apps produced no entries at all and passed as admissible. The detector
# is now structural (any dict-of-dicts is a container), no allowlist needed.
# ---------------------------------------------------------------------------

def _gmail_shaped_env(message_ids):
    return {
        "LightGmail": {
            "status": "ok",
            "output": {
                "messages": {mid: {"subject": "hi", "from": "a@b.com"} for mid in message_ids},
                "drafts": {},
                "labels": {"INBOX": {"name": "Inbox"}},
            },
        },
    }


def test_world_mismatch_catches_non_allowlisted_app():
    gt = _gmail_shaped_env(["msg-woodworks-1", "msg-woodworks-2"])
    # Same schema, completely disjoint entity ids -> a different seeded world
    # (e.g. served under a different default company/org than gt was baked
    # against), exactly the "orbit-labs vs woodworks" substitution scenario.
    wrong_world = _gmail_shaped_env(["msg-orbit-labs-9", "msg-orbit-labs-10"])
    assert _world_mismatch(wrong_world, gt) is True

    same_world = _gmail_shaped_env(["msg-woodworks-1", "msg-woodworks-2"])
    assert _world_mismatch(same_world, gt) is False


def test_ids_by_container_buckets_arbitrary_container_names():
    env = _gmail_shaped_env(["m1", "m2"])
    acc = _ids_by_container(env)
    # "messages" was never in the old _CONTAINER_KEYS allowlist.
    assert acc["messages"] == {"m1", "m2"}
    assert acc["labels"] == {"INBOX"}


def test_state_admissibility_flags_world_mismatch_for_non_allowlisted_app():
    gt = _gmail_shaped_env(["msg-woodworks-1"])
    old = _gmail_shaped_env([])
    wrong_world = _gmail_shaped_env(["msg-orbit-labs-9"])
    ok, reason = state_admissibility(old, wrong_world, gt)
    assert ok is False
    assert "world_mismatch" in reason
