"""Tests for the in-process multi-app state baker (benchmark/bake_state_mcp.py).

Uses stub sessions (patched into _boot) so the guard logic is covered without
booting the real seeded world.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import benchmark.bake_state_mcp as B


class _StubSession:
    """A tiny session whose get_session_dict() returns the LIVE dict (like the
    real sessions) so the baker's snapshot/aliasing handling is exercised."""
    def __init__(self, state):
        self.state = state

    def get_session_dict(self):
        return self.state          # live reference, intentionally

    def do_write(self, key, value):
        self.state[key] = value
        return {"status": "ok"}

    def do_fail(self):
        return {"status": "error", "output": "nope"}


def _patch(monkeypatch, sessions):
    monkeypatch.setattr(B, "_boot", lambda app, seed: sessions[app])


def _write_oracle(tmp_path, spec):
    d = tmp_path / "tests"
    d.mkdir(parents=True, exist_ok=True)
    (d / "oracle.json").write_text(json.dumps(spec))
    return tmp_path


def test_bake_snapshots_and_detects_change(tmp_path, monkeypatch):
    sess = _StubSession({"pages": {"p1": {"text": "old"}}})
    _patch(monkeypatch, {"App": sess})
    task = _write_oracle(tmp_path, {
        "seed": 1, "apps": ["App"],
        "oracle": {"App": [{"call": "do_write", "args": {"key": "new", "value": 1}}]},
    })
    old, gt = B.bake(str(task))
    # Snapshot isolation: old must NOT show the post-oracle write (the aliasing bug).
    assert "new" not in old["App"]["output"]
    assert gt["App"]["output"]["new"] == 1
    # Files written in the facade-compatible {app: {status, output}} schema.
    assert json.loads((task / "tests" / "old_env.json").read_text())["App"]["status"] == "ok"
    assert json.loads((task / "tests" / "gt_env.json").read_text())["App"]["output"]["new"] == 1


def test_bake_rejects_empty_dump(tmp_path, monkeypatch):
    _patch(monkeypatch, {"App": _StubSession({})})       # empty world
    task = _write_oracle(tmp_path, {"seed": 1, "apps": ["App"], "oracle": {}})
    with pytest.raises(SystemExit, match="empty dump"):
        B.bake(str(task))


def test_bake_rejects_noop_oracle(tmp_path, monkeypatch):
    _patch(monkeypatch, {"App": _StubSession({"pages": {"p1": 1}})})
    task = _write_oracle(tmp_path, {"seed": 1, "apps": ["App"], "oracle": {}})
    with pytest.raises(SystemExit, match="changed nothing"):
        B.bake(str(task))


def test_bake_aborts_on_failed_write(tmp_path, monkeypatch):
    _patch(monkeypatch, {"App": _StubSession({"pages": {"p1": 1}})})
    task = _write_oracle(tmp_path, {
        "seed": 1, "apps": ["App"],
        "oracle": {"App": [{"call": "do_fail", "args": {}}]},
    })
    with pytest.raises(SystemExit, match="failed"):
        B.bake(str(task))


def _msg_env(id_, from_addr, subject, snippet):
    return {"App": {"status": "ok", "output": {"messages": [{
        "id": id_, "thread_id": f"thr-{id_}",
        "from_addr": from_addr, "subject": subject, "snippet": snippet,
    }]}}}


def test_repair_new_env_rejects_replay_that_succeeds_against_wrong_entities(monkeypatch):
    # The empty-dump branch's own docstring warning: a replayed call can keep
    # gt_env's ids but "succeed against the wrong entities" -- same id, unrelated
    # content. _world_mismatch (id-set disjointness) can't see this; only the
    # content check can. Reproduces a same-id-different-content substitution
    # at this call site specifically (bake_state_mcp calls _world_mismatch
    # directly, not through state_admissibility).
    gt = _msg_env("msg-101", "sender-a@example.com",
                  "Subject A",
                  "Content belonging to world A.")
    old = _msg_env("msg-101", "sender-a@example.com",
                   "Subject A",
                   "Content belonging to world A.")
    empty_new = {"App": {"status": "ok", "output": {}}}
    wrong_content_replay = _msg_env("msg-101", "sender-b@example.com",
                                     "Subject B",
                                     "Unrelated content from world B.")

    monkeypatch.setattr(B, "replay_trajectory",
                         lambda task_dir, trajectory, seed=None: (wrong_content_replay, 1))

    rebuilt, info = B.repair_new_env("task_dir", empty_new, old, gt, trajectory=[], seed=1)
    assert info["repaired"] is False
    assert info["reason"] == "empty_dump+replay_content_mismatch"
    assert rebuilt == empty_new  # not swapped in


def test_repair_new_env_accepts_replay_matching_gt_content(monkeypatch):
    gt = _msg_env("msg-101", "sender-a@example.com",
                  "Subject A",
                  "Content belonging to world A.")
    old = {"App": {"status": "ok", "output": {"messages": []}}}
    empty_new = {"App": {"status": "ok", "output": {}}}
    good_replay = _msg_env("msg-101", "sender-a@example.com",
                           "Subject A",
                           "Content belonging to world A.")

    monkeypatch.setattr(B, "replay_trajectory",
                         lambda task_dir, trajectory, seed=None: (good_replay, 1))

    rebuilt, info = B.repair_new_env("task_dir", empty_new, old, gt, trajectory=[], seed=1)
    assert info["repaired"] is True
    assert rebuilt == good_replay
