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
