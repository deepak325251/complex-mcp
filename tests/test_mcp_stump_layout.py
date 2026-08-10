from __future__ import annotations

import json
from pathlib import Path

from scripts.task_writer import (
    _mcp_stump_slug,
    _next_run_number,
    write_mcp_stump_run,
    write_trials_aggregate,
)


def _record(name="mcp-stump/insider-liquidation-refusal", index=1, seed=777,
            apps=None, output="<tool>{\"name\":\"do\",\"arguments\":{}}</tool>\n<response>{}</response>\nfinal.\n"):
    return {
        "index": index,
        "name": name,
        "query": "Please do the thing.",
        "seed": seed,
        "apps": apps or [],
        "level": None,
        "tool_cnt": {"do": {"ok": 1}},
        "tokens": {"prompt": 10, "llm": 20, "tool": 30},
        "valid_tool_calls": 1,
        "invalid_tool_calls": 0,
        "error_tool_calls": 0,
        "output": output,
        "old_env": {"LightShop": {"balance": 100}},
        "new_env": {"LightShop": {"balance": 100}},
    }


def test_slug_strips_mcp_stump_prefix():
    assert _mcp_stump_slug("mcp-stump/insider-liquidation-refusal") == "insider-liquidation-refusal"


def test_slug_keeps_non_prefixed_names():
    name = "complexmcp-l4-s42-weather-contingent-rebooking-000"
    assert _mcp_stump_slug(name) == name


def test_next_run_number_empty(tmp_path: Path):
    assert _next_run_number(tmp_path / "does-not-exist") == 1


def test_next_run_number_increments(tmp_path: Path):
    (tmp_path / "run_1").mkdir()
    (tmp_path / "run_2").mkdir()
    (tmp_path / "run_7").mkdir()
    assert _next_run_number(tmp_path) == 8


def test_write_mcp_stump_run_creates_all_files(tmp_path: Path):
    rec = _record()
    score = {"gradeable": True, "reward": 1.0, "recall": 3, "total": 3,
             "misbehave": 0, "passed": True}
    run_dir, final = write_mcp_stump_run(tmp_path, rec, model="claude-opus-4-8",
                                         score=score)
    assert run_dir.exists()
    assert run_dir.parent.name == "claude-opus-4-8"
    assert run_dir.parent.parent.name == "trajectories"
    assert run_dir.parent.parent.parent.name == "trials_insider-liquidation-refusal"
    for f in ["trajectory.json", "agent.log", "initial_state.json",
              "final_state.json", "trace.jsonl", "reward.json", "reward.txt",
              "diagnosis.json", "report.json"]:
        assert (run_dir / f).exists(), f"missing {f}"
    reward_txt = (run_dir / "reward.txt").read_text().strip()
    assert float(reward_txt) == 1.0
    report = json.loads((run_dir / "report.json").read_text())
    assert report["passed"] is True
    assert report["model"] == "claude-opus-4-8"
    assert report["seed"] == 777


def test_write_mcp_stump_run_auto_increments(tmp_path: Path):
    rec = _record()
    score = {"gradeable": True, "reward": 0.0, "recall": 0, "total": 3,
             "misbehave": 0, "passed": False}
    r1, _ = write_mcp_stump_run(tmp_path, rec, model="claude-opus-4-8", score=score)
    r2, _ = write_mcp_stump_run(tmp_path, rec, model="claude-opus-4-8", score=score)
    assert r1.name == "run_1"
    assert r2.name == "run_2"


def test_write_mcp_stump_run_emits_rubric_detail_ctrf(tmp_path: Path):
    rec = _record()
    score = {"gradeable": True, "reward": 1.0, "recall": 3, "total": 3,
             "misbehave": 0, "passed": True}
    rubric_result = {
        "format": "mcp-stump",
        "rubric_score": 1.0,
        "rc": 1.0,
        "rb": 0.0,
        "passed": True,
        "per_criterion": [
            {"number": 1, "criterion": "did X", "is_positive": True,
             "satisfied": True, "justification": "yes"},
            {"number": 2, "criterion": "avoided Y", "is_positive": False,
             "satisfied": False, "justification": "no"},
        ],
    }
    run_dir, _ = write_mcp_stump_run(tmp_path, rec, model="claude-opus-4-8",
                                     score=score, rubric_result=rubric_result)
    assert (run_dir / "rubric.json").exists()
    assert (run_dir / "detail.json").exists()
    assert (run_dir / "ctrf.json").exists()
    rubric_out = json.loads((run_dir / "rubric.json").read_text())
    assert rubric_out["rubric_score"] == 1.0
    detail = json.loads((run_dir / "detail.json").read_text())
    assert detail["rubric"]["format"] == "mcp-stump"
    assert detail["rubric"]["rubric_score"] == 1.0
    ctrf = json.loads((run_dir / "ctrf.json").read_text())
    assert ctrf["results"]["tool"]["name"] == "complexmcp-benchmark"
    assert ctrf["results"]["summary"]["tests"] == 3
    assert ctrf["results"]["extra"]["task"] == rec["name"]


def test_write_mcp_stump_run_copies_ground_truth(tmp_path: Path):
    task_dir_source = tmp_path / "src_task"
    (task_dir_source / "tests").mkdir(parents=True)
    (task_dir_source / "tests" / "gt_env.json").write_text('{"k":"v"}')
    output_root = tmp_path / "out"
    rec = _record()
    score = {"gradeable": True, "reward": 1.0, "recall": 1, "total": 1,
             "misbehave": 0, "passed": True}
    run_dir, _ = write_mcp_stump_run(output_root, rec, model="claude-opus-4-8",
                                     score=score, task_dir_source=str(task_dir_source))
    gt = run_dir.parent.parent.parent / "ground_truth" / "gt_env.json"
    assert gt.exists()
    assert json.loads(gt.read_text()) == {"k": "v"}


def test_write_trials_aggregate_writes_summary_pairs_failures(tmp_path: Path):
    runs = [
        {"seed": 777, "passed": True, "reward": 1.0, "completion_rate": 1.0,
         "misbehaving_rate": 0.0, "query": "q", "final_message": "done"},
        {"seed": 777, "passed": False, "reward": 0.0, "completion_rate": 0.0,
         "misbehaving_rate": 0.0, "failure_class": "refused",
         "reason": "did not attempt", "query": "q", "final_message": "no"},
    ]
    trials_dir = write_trials_aggregate(tmp_path, "mcp-stump/foo", "claude-opus-4-8",
                                        runs, instruction="Do it.")
    assert trials_dir.name == "trials_foo"
    summary = json.loads((trials_dir / "summary.json").read_text())
    assert summary["metrics"]["n"] == 2
    assert summary["metrics"]["c"] == 1
    assert summary["metrics"]["pass@1"] == 0.5
    pairs = (trials_dir / "pairs.jsonl").read_text().strip().splitlines()
    assert len(pairs) == 2
    p0 = json.loads(pairs[0])
    assert p0["instruction"] == "Do it."
    failures = json.loads((trials_dir / "failure_analysis.json").read_text())
    assert len(failures) == 1
    assert failures[0]["failure_class"] == "refused"
