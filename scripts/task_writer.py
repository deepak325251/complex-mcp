from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.classify_failure import classify, parse_expected_tools  # noqa: E402


_TOOL_RE = re.compile(r"<tool>\s*(\{.*?\})\s*</tool>", re.DOTALL)
_RESP_RE = re.compile(r"<response>\s*(.*?)\s*</response>", re.DOTALL)


def _slug(name: str, maxlen: int = 40) -> str:
    core = re.sub(r"^complexmcp-l\d+-s\d+-", "", name)
    core = re.sub(r"-\d{3}$", "", core)
    core = re.sub(r"[^A-Za-z0-9]+", "-", core).strip("-").lower()
    return core[:maxlen] or "task"


def parse_trajectory(output: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    pos = 0
    step_no = 0
    while True:
        tm = _TOOL_RE.search(output, pos)
        if not tm:
            break
        step_no += 1
        reasoning = output[pos:tm.start()].strip()
        tool_json = tm.group(1)
        try:
            tool_data = json.loads(tool_json)
            tool_name = tool_data.get("name")
            tool_args = tool_data.get("arguments", {})
        except json.JSONDecodeError:
            tool_name = None
            tool_args = tool_json

        rm = _RESP_RE.search(output, tm.end())
        if rm and rm.start() - tm.end() < 80:
            response_raw = rm.group(1)
            try:
                response: Any = json.loads(response_raw)
            except json.JSONDecodeError:
                response = response_raw
            pos = rm.end()
        else:
            response = None
            pos = tm.end()

        steps.append({
            "step": step_no,
            "reasoning": reasoning,
            "tool": tool_name,
            "arguments": tool_args,
            "response": response,
        })
    final_message = output[pos:].strip()
    return {"steps": steps, "final_message": final_message}


def render_output_md(record: dict, traj: dict) -> str:
    lines = [
        f"# Task {record['index']}: {record['name']}",
        "",
        f"- **Query**: {record['query']}",
        f"- **Seed**: {record['seed']}",
        f"- **Apps**: {', '.join(record.get('apps', []))}",
        f"- **Level**: {record.get('level')}",
        f"- **Tool calls**: valid={record['valid_tool_calls']} "
        f"invalid={record['invalid_tool_calls']} error={record['error_tool_calls']}",
        f"- **Tokens**: prompt={record['tokens'].get('prompt')} "
        f"llm={record['tokens'].get('llm')} tool={record['tokens'].get('tool')}",
        "",
        "---",
        "",
        f"## Trajectory ({len(traj['steps'])} tool calls)",
        "",
    ]
    for s in traj["steps"]:
        if s["reasoning"]:
            lines += [f"### Step {s['step']} — reasoning", "", s["reasoning"], ""]
        lines += [
            f"### Step {s['step']} — call `{s['tool']}`",
            "",
            "```json",
            json.dumps(s["arguments"], indent=2, ensure_ascii=False),
            "```",
            "",
            f"### Step {s['step']} — response",
            "",
            "```json",
            json.dumps(s["response"], indent=2, ensure_ascii=False)
                if not isinstance(s["response"], str) else s["response"],
            "```",
            "",
        ]
    if traj["final_message"]:
        lines += ["## Final message", "", traj["final_message"], ""]
    return "\n".join(lines)


def write_task_dir(tasks_root: Path, record: dict, *,
                   score: dict | None = None,
                   task_context: dict | None = None) -> tuple[Path, dict]:
    slug = _slug(record["name"])
    task_dir = tasks_root / f"task_{record['index']:03d}__{slug}"
    task_dir.mkdir(parents=True, exist_ok=True)

    meta = {k: record[k] for k in ("index", "name", "query", "seed", "apps", "level")}
    (task_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    traj = parse_trajectory(record.get("output", ""))
    (task_dir / "trajectory.json").write_text(json.dumps(traj, indent=2, ensure_ascii=False))
    (task_dir / "output.md").write_text(render_output_md(record, traj))

    tool_summary = {
        "tool_cnt": record.get("tool_cnt", {}),
        "valid_tool_calls": record["valid_tool_calls"],
        "invalid_tool_calls": record["invalid_tool_calls"],
        "error_tool_calls": record["error_tool_calls"],
    }
    (task_dir / "tool_summary.json").write_text(json.dumps(tool_summary, indent=2))
    (task_dir / "tokens.json").write_text(json.dumps(record.get("tokens", {}), indent=2))

    if score is None:
        score = {
            "gradeable": False,
            "reason": "Harbor tasks in benchmark/harbor_final_all/ have no gt_env.json "
                      "(needs tests/gen_gt.py replay of solution/trajectory.json).",
            "reward": None,
            "recall": None,
            "misbehave": None,
            "total": None,
        }

    passed = bool(score.get("passed", False))
    if not passed:
        ctx = dict(task_context or {})
        if "expected_tools" not in ctx and record.get("expected_tool_calls"):
            ctx["expected_tools"] = parse_expected_tools(record.get("expected_tool_calls"))
        verdict = classify(
            trajectory=traj,
            tool_summary=tool_summary,
            score=score,
            task_context=ctx,
            final_message=traj.get("final_message"),
        )
        score = {**score, **verdict.to_dict()}

    (task_dir / "score.json").write_text(json.dumps(score, indent=2))

    return task_dir, score


def _mcp_stump_slug(name: str) -> str:
    if name.startswith("mcp-stump/"):
        return name.split("/", 1)[1]
    return name


def _next_run_number(model_dir: Path) -> int:
    if not model_dir.exists():
        return 1
    existing = [d.name for d in model_dir.iterdir()
                if d.is_dir() and d.name.startswith("run_")]
    nums = []
    for n in existing:
        try:
            nums.append(int(n.split("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    return (max(nums) + 1) if nums else 1


_GT_FILES = (
    "expected_state.json",
    "gold_plan.json",
    "initial_state.json",
    "judge_spec.json",
    "gt_env.json",
)


def _write_ground_truth(trials_dir: Path, task_dir_source: str | Path | None) -> None:
    if not task_dir_source:
        return
    tests_dir = Path(task_dir_source) / "tests"
    if not tests_dir.exists():
        return
    gt_dir = trials_dir / "ground_truth"
    for name in _GT_FILES:
        src = tests_dir / name
        if not src.exists():
            continue
        gt_dir.mkdir(parents=True, exist_ok=True)
        dest = gt_dir / name
        if not dest.exists():
            dest.write_text(src.read_text())


def _write_rubric_json(run_dir: Path, rubric_result: dict | None) -> None:
    if not rubric_result:
        return
    (run_dir / "rubric.json").write_text(
        json.dumps(rubric_result, indent=2, ensure_ascii=False, default=str)
    )


def _write_detail_json(run_dir: Path, score: dict, rubric_result: dict | None,
                       tool_summary: dict) -> None:
    detail = {
        "reward": score.get("reward"),
        "recall": score.get("recall"),
        "total": score.get("total"),
        "misbehave": score.get("misbehave"),
        "passed": bool(score.get("passed")),
        "gradeable": bool(score.get("gradeable")),
        "tool_summary": tool_summary,
    }
    if rubric_result:
        detail["rubric"] = {
            "format": rubric_result.get("format"),
            "rubric_score": rubric_result.get("rubric_score"),
            "rc": rubric_result.get("rc"),
            "rb": rubric_result.get("rb"),
            "passed": rubric_result.get("passed"),
            "per_check": rubric_result.get("per_check"),
            "per_criterion": rubric_result.get("per_criterion"),
        }
    (run_dir / "detail.json").write_text(
        json.dumps(detail, indent=2, ensure_ascii=False, default=str)
    )


def _write_ctrf_json(run_dir: Path, task_name: str, model: str, run_no: int,
                     score: dict, rubric_result: dict | None) -> None:
    from datetime import datetime, timezone
    passed = bool(score.get("passed"))
    tests = [{
        "name": f"{task_name}#reward",
        "status": "passed" if passed else "failed",
        "duration": 0,
    }]
    if rubric_result and "per_criterion" in rubric_result:
        for c in rubric_result["per_criterion"]:
            tests.append({
                "name": f"{task_name}#rubric.{c.get('number')}",
                "status": "passed" if c.get("satisfied") else "failed",
                "duration": 0,
                "message": c.get("justification", ""),
            })
    elif rubric_result and "per_check" in rubric_result:
        for c in rubric_result["per_check"]:
            tests.append({
                "name": f"{task_name}#rubric.{c.get('check_id')}",
                "status": "passed" if c.get("passed") else "failed",
                "duration": 0,
                "message": c.get("reason", ""),
            })
    summary_passed = sum(1 for t in tests if t["status"] == "passed")
    ctrf = {
        "results": {
            "tool": {"name": "complexmcp-benchmark"},
            "summary": {
                "tests": len(tests),
                "passed": summary_passed,
                "failed": len(tests) - summary_passed,
                "pending": 0, "skipped": 0, "other": 0,
                "start": 0,
                "stop": int(datetime.now(timezone.utc).timestamp()),
            },
            "tests": tests,
            "extra": {"task": task_name, "model": model, "attempt": run_no},
        }
    }
    (run_dir / "ctrf.json").write_text(
        json.dumps(ctrf, indent=2, ensure_ascii=False, default=str)
    )


def write_mcp_stump_run(output_root: Path, record: dict, *,
                        model: str, score: dict | None = None,
                        task_context: dict | None = None,
                        rubric_result: dict | None = None,
                        task_dir_source: str | Path | None = None) -> tuple[Path, dict]:
    slug = _mcp_stump_slug(record["name"])
    trials_dir = output_root / f"trials_{slug}"
    model_dir = trials_dir / "trajectories" / model
    run_no = _next_run_number(model_dir)
    run_dir = model_dir / f"run_{run_no}"
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_ground_truth(trials_dir, task_dir_source)

    traj = parse_trajectory(record.get("output", ""))
    (run_dir / "trajectory.json").write_text(
        json.dumps(traj, indent=2, ensure_ascii=False))

    (run_dir / "agent.log").write_text(record.get("output", ""))

    (run_dir / "initial_state.json").write_text(
        json.dumps(record.get("old_env") or {}, indent=2, ensure_ascii=False, default=str))
    (run_dir / "final_state.json").write_text(
        json.dumps(record.get("new_env") or {}, indent=2, ensure_ascii=False, default=str))

    (run_dir / "trace.jsonl").write_text("")

    if score is None:
        score = {
            "gradeable": False, "reward": None,
            "recall": None, "misbehave": None, "total": None,
        }

    passed = bool(score.get("passed", False))
    tool_summary = {
        "tool_cnt": record.get("tool_cnt", {}),
        "valid_tool_calls": record["valid_tool_calls"],
        "invalid_tool_calls": record["invalid_tool_calls"],
        "error_tool_calls": record["error_tool_calls"],
    }
    if not passed:
        ctx = dict(task_context or {})
        if "expected_tools" not in ctx and record.get("expected_tool_calls"):
            ctx["expected_tools"] = parse_expected_tools(record.get("expected_tool_calls"))
        verdict = classify(
            trajectory=traj,
            tool_summary=tool_summary,
            score=score,
            task_context=ctx,
            final_message=traj.get("final_message"),
        )
        score = {**score, **verdict.to_dict()}

    reward = score.get("reward")
    reward_val = float(reward) if reward is not None else 0.0
    (run_dir / "reward.json").write_text(json.dumps({
        "reward": reward_val,
        "total": score.get("total"),
        "recall": score.get("recall"),
        "misbehave": score.get("misbehave"),
    }, indent=2))
    (run_dir / "reward.txt").write_text(f"{reward_val}\n")

    (run_dir / "diagnosis.json").write_text(json.dumps({
        "failure_class": score.get("failure_class"),
        "reason": score.get("reason"),
        "evidence": score.get("evidence"),
    }, indent=2, ensure_ascii=False))

    total = score.get("total") or 0
    recall = score.get("recall") or 0
    misbehave = score.get("misbehave") or 0
    completion_rate = (recall / total) if total else (1.0 if passed else 0.0)
    misbehaving_rate = (misbehave / total) if total else 0.0
    (run_dir / "report.json").write_text(json.dumps({
        "task": record["name"],
        "model": model,
        "seed": record.get("seed"),
        "attempt": run_no,
        "passed": passed,
        "reward": reward_val,
        "completion_rate": completion_rate,
        "misbehaving_rate": misbehaving_rate,
        "tokens": record.get("tokens", {}),
        "tool_summary": tool_summary,
    }, indent=2, ensure_ascii=False))

    _write_rubric_json(run_dir, rubric_result)
    _write_detail_json(run_dir, score, rubric_result, tool_summary)
    _write_ctrf_json(run_dir, record["name"], model, run_no, score, rubric_result)

    return run_dir, score


def write_trials_aggregate(output_root: Path, task_name: str, model: str,
                           run_records: list[dict], *,
                           instruction: str | None = None) -> Path:
    slug = _mcp_stump_slug(task_name)
    trials_dir = output_root / f"trials_{slug}"
    trials_dir.mkdir(parents=True, exist_ok=True)

    n = len(run_records)
    c = sum(1 for r in run_records if r.get("passed"))
    pass_at_1 = (c / n) if n else 0.0

    from datetime import datetime, timezone
    summary = {
        "task": task_name,
        "model": model,
        "agent": "claude-code",
        "seed": run_records[0].get("seed") if run_records else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {"n": n, "c": c, "pass@1": pass_at_1},
        "attempts": [
            {
                "attempt": i + 1,
                "passed": bool(r.get("passed")),
                "reward": r.get("reward"),
                "completion_rate": r.get("completion_rate"),
                "misbehaving_rate": r.get("misbehaving_rate"),
            }
            for i, r in enumerate(run_records)
        ],
    }
    (trials_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))

    pairs_lines = []
    for i, r in enumerate(run_records):
        pairs_lines.append(json.dumps({
            "task": task_name,
            "seed": r.get("seed"),
            "attempt": i + 1,
            "instruction": instruction or r.get("query", ""),
            "response": r.get("final_message", ""),
        }, ensure_ascii=False))
    (trials_dir / "pairs.jsonl").write_text("\n".join(pairs_lines) + "\n"
                                            if pairs_lines else "")

    failures = [
        {
            "attempt": i + 1,
            "failure_class": r.get("failure_class"),
            "reason": r.get("reason"),
        }
        for i, r in enumerate(run_records)
        if not r.get("passed")
    ]
    (trials_dir / "failure_analysis.json").write_text(
        json.dumps(failures, indent=2, ensure_ascii=False))

    return trials_dir
