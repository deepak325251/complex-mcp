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
