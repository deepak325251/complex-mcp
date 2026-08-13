"""Layer-1: reconstruct new_env by replaying the trajectory in-process."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from benchmark.bake_state_mcp import replay_trajectory, repair_new_env, _split_tool
from benchmark.weighted_judge import judge_env, state_admissibility

TASK = "bundle/input/02-auth-v2-rollout-coordination"


def test_split_tool():
    apps = ["LightNotion", "LightSlack"]
    assert _split_tool("LightNotion_append_block_children", apps) == ("LightNotion", "append_block_children")
    assert _split_tool("LightSlack::chat_post_message", apps) == ("LightSlack", "chat_post_message")


def test_repair_empty_facade_dump():
    if not os.path.isdir(TASK):
        return
    old = json.load(open(f"{TASK}/tests/old_env.json"))
    gt = json.load(open(f"{TASK}/tests/gt_env.json"))
    empty = {a: {"status": "ok", "output": {}} for a in old}
    assert state_admissibility(old, empty, gt)[0] is False   # broken to start

    traj = {"steps": [
        {"tool": "LightNotion_append_block_children",
         "arguments": {"parent_id": "page-meeting-001",
                       "children": [{"type": "bulleted_list_item",
                                     "text": "Runbook drift dual-writer"}]}},
        {"tool": "LightSlack_chat_post_message",
         "arguments": {"channel": "C01AUTHV2",
                       "text": "runbook <@U01AMELIA> <@U01JONAS>"}},
    ]}
    fixed, info = repair_new_env(TASK, empty, old, gt, traj)
    assert info["repaired"] is True and info["calls_applied"] == 2
    ok, _ = state_admissibility(old, fixed, gt)
    assert ok is True                                        # now gradable
    # did-nothing agent rebuilds an unchanged world -> zero completion
    fixed2, _ = repair_new_env(TASK, empty, old, gt,
                               {"steps": [{"tool": "LightJira_list_sprints", "arguments": {}}]})
    s = judge_env(old, fixed2, gt)
    assert s["recall"] == 0


def test_good_dump_not_touched():
    if not os.path.isdir(TASK):
        return
    old = json.load(open(f"{TASK}/tests/old_env.json"))
    gt = json.load(open(f"{TASK}/tests/gt_env.json"))
    # a fine dump (gt itself) must pass through unchanged, not be rebuilt
    fixed, info = repair_new_env(TASK, gt, old, gt, {"steps": []})
    assert info["repaired"] is False
