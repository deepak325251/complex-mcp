"""The mcp-stump layout must not change, and `.raw` must keep everything.

`--layout harbor` ADDS a tree; it must not alter the one that already ships.
The reshape has no slot for pairs.jsonl, diagnosis.json, trace.jsonl or the
world snapshots -- and pairs.jsonl is the training deliverable -- so `.raw`
holds the mcp-stump output verbatim beside the Harbor files.
"""

import json
from pathlib import Path

import pytest

from scripts.task_writer import write_mcp_stump_run


RECORD = {
    "name": "mcp-stump/demo-task", "output": "", "query": "do the thing",
    "valid_tool_calls": 3, "invalid_tool_calls": 0, "error_tool_calls": 0,
    "tool_cnt": {"now": {"ok": 1}}, "seed": 4127, "tokens": {"prompt": 10},
    "usage": {"input_tokens": 10, "output_tokens": 2}, "old_env": {"a": 1},
    "new_env": {"a": 2}, "termination_reason": "end_tag",
}
SCORE = {"gradeable": True, "reward": 0.5, "recall": 1, "total": 2,
         "misbehave": 0, "passed": False,
         "passed_tests": {"test_a": True, "test_guard_b": False},
         "pytest_checks": {"weighted_score": 0.5,
                           "tests": [{"name": "test_a", "weight": 1.0, "passed": True}]}}


def _write(root: Path):
    return write_mcp_stump_run(root, RECORD, model="m", score=dict(SCORE))


# Files carrying intrinsic per-run identity, so not byte-comparable:
#   ctrf.json                  wall-clock `summary.stop`
#   trajectory.messages.json   freshly minted session_id + timestamp
_NONDETERMINISTIC = {"ctrf.json", "trajectory.messages.json"}


def test_layout_is_deterministic_across_roots(tmp_path):
    """Same inputs, two roots -> identical bytes. Pins the format so a future
    change to the Harbor writer cannot quietly alter this one."""
    a, _ = _write(tmp_path / "a")
    b, _ = _write(tmp_path / "b")
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    compared = 0
    for rel in files:
        if rel.name in _NONDETERMINISTIC:
            continue
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel
        compared += 1
    assert compared >= 8       # exclusions must not hollow the test out


def test_mcp_stump_run_still_emits_its_full_file_set(tmp_path):
    run_dir, _ = _write(tmp_path)
    for rel in ("report.json", "reward.json", "reward.txt", "detail.json",
                "ctrf.json", "diagnosis.json", "initial_state.json",
                "final_state.json", "trace.jsonl", "agent.log",
                "agent/trajectory.json", "agent/trajectory.messages.json"):
        assert (run_dir / rel).is_file(), rel


def test_raw_subtree_keeps_the_training_deliverables(tmp_path):
    """What `.raw` exists to preserve: the files the Harbor shape has no slot for."""
    job = tmp_path / "task-slug"
    run_dir, _ = write_mcp_stump_run(job / ".raw", RECORD, model="m", score=dict(SCORE))
    assert ".raw" in run_dir.parts
    for rel in ("diagnosis.json", "trace.jsonl", "initial_state.json",
                "final_state.json"):
        assert (run_dir / rel).is_file(), rel


def test_raw_sits_beside_the_harbor_tree_not_inside_it(tmp_path):
    from benchmark.harbor_layout import write_harbor_trial
    job = tmp_path / "task-slug"
    write_mcp_stump_run(job / ".raw", RECORD, model="m", score=dict(SCORE))
    (tmp_path / "t" / "tests").mkdir(parents=True)
    write_harbor_trial(job, 1, record=RECORD, model="m",
                       judge_result={"reward": 0.5, "traj_tests": {}},
                       task_dir=tmp_path / "t", grading_dir=tmp_path / "t" / "tests",
                       job_id="j", job_label="l")
    assert (job / ".raw").is_dir() and (job / "trajectory" / "Run 1").is_dir()
    # Neither tree is nested inside the other.
    assert not (job / "trajectory" / ".raw").exists()
    assert not any(p.name == "trajectory" for p in (job / ".raw").rglob("*"))


def test_run_numbers_increment_across_attempts(tmp_path):
    r1, _ = _write(tmp_path)
    r2, _ = _write(tmp_path)
    assert r1.name == "run_1" and r2.name == "run_2"


def test_corpus_rollup_finds_trials_in_both_layouts(tmp_path):
    """`passk_summary.json` globbed only the flat mcp-stump form, so every
    harbor run reported 0 tasks / accuracy 0.0 as though it were a result."""
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location(
        "_rb", Path(__file__).resolve().parent.parent / "run_benchmark.py")
    rb = importlib.util.module_from_spec(spec)
    sys.modules["_rb"] = rb
    spec.loader.exec_module(rb)

    summary = {"task": "t", "metrics": {"n": 1, "c": 1, "pass@k": {}, "pass^k": {},
                                        "failure_breakdown": {}},
               "attempts": [{"passed": True, "reward": 1.0}]}
    flat = tmp_path / "trials_a"
    flat.mkdir(parents=True)
    (flat / "summary.json").write_text(json.dumps(summary))
    nested = tmp_path / "task-slug" / ".raw" / "trials_b"
    nested.mkdir(parents=True)
    (nested / "summary.json").write_text(json.dumps(dict(summary, task="u")))

    out = rb._aggregate_trials_on_disk(tmp_path, "m")
    assert out["tasks"] == 2
    assert {t["task"] for t in out["per_task"]} == {"t", "u"}
