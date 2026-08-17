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


def test_repair_new_env_rejects_world_mismatched_replay(monkeypatch):
    """repair_new_env must not swap an empty dump for an *unverified* replay.

    If the trajectory was recorded against a differently-seeded live world
    (the seed-plumbing bug), replaying it in-process at the *correct* seed
    still won't land on gt_env's entities. This reproduces that: the replay
    comes back non-empty but with an entity-id set disjoint from gt_env's —
    repair_new_env must refuse it rather than accept any non-empty rebuild."""
    import benchmark.bake_state_mcp as bsm

    gt = {"LightGmail": {"status": "ok", "output": {
        "messages": {"msg-woodworks-1": {"subject": "hi"}}}}}
    old = {"LightGmail": {"status": "ok", "output": {"messages": {}}}}
    empty = {"LightGmail": {"status": "ok", "output": {}}}
    wrong_world_replay = {"LightGmail": {"status": "ok", "output": {
        "messages": {"msg-orbit-labs-9": {"subject": "hi"}}}}}

    monkeypatch.setattr(bsm, "replay_trajectory",
                         lambda *a, **k: (wrong_world_replay, 1))

    fixed, info = bsm.repair_new_env(TASK, empty, old, gt, {"steps": [
        {"tool": "LightGmail_send", "arguments": {}}]})
    assert info["repaired"] is False
    assert info["reason"] == "empty_dump+replay_world_mismatch"
    assert fixed == empty  # falls back to the (honestly empty) dump, not the bad replay


def test_repair_new_env_accepts_matching_replay(monkeypatch):
    """Sanity check: a replay that DOES land on gt_env's entities is still
    accepted on an empty dump — the new guard only rejects mismatched worlds."""
    import benchmark.bake_state_mcp as bsm

    gt = {"LightGmail": {"status": "ok", "output": {
        "messages": {"msg-woodworks-1": {"subject": "hi"}}}}}
    old = {"LightGmail": {"status": "ok", "output": {"messages": {}}}}
    empty = {"LightGmail": {"status": "ok", "output": {}}}
    matching_replay = {"LightGmail": {"status": "ok", "output": {
        "messages": {"msg-woodworks-1": {"subject": "hi"}}}}}

    monkeypatch.setattr(bsm, "replay_trajectory",
                         lambda *a, **k: (matching_replay, 1))

    fixed, info = bsm.repair_new_env(TASK, empty, old, gt, {"steps": [
        {"tool": "LightGmail_send", "arguments": {}}]})
    assert info["repaired"] is True
    assert fixed == matching_replay
