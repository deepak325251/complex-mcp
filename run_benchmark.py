from client.agent import OpenAIBackend, HumanAnnotator, AgentClient, Toolbox
from client.rag import ChromaRAG
from benchmark.judge import judge_env
from benchmark.rubric_judge import evaluate_rubric, find_rubric_for_task, load_rubric
from benchmark.pytest_api import load_checks_from_file, run_checks
from scripts.task_writer import write_task_dir, write_mcp_stump_run, write_trials_aggregate, parse_trajectory as _parse_traj_for_layout, parse_trajectory
from dotenv import load_dotenv
from argparse import ArgumentParser
from prompt_toolkit import prompt
from typing import Dict, Any
from pathlib import Path
import random
import json

import sys
import os
import re
import yaml
import asyncio
from collections import Counter
from datetime import datetime

import pandas as pd
from shortuuid import uuid

def parse_toolbox(tool_config_path: str | Path, method: str, rag_conf: Dict = {}):
    config = {}
    with open(tool_config_path) as f:
        data = yaml.safe_load(f)
        config["servers"] = data["servers"]

    toolbox = Toolbox(method=method) if method not in ["rag", "fetch"] else Toolbox(method=method, rag_cls=ChromaRAG, default_k=rag_conf["topk"])
    skipped = []
    for server in config["servers"]:
        if not server["use"]: continue
        server_args = {
            "server_name": server["name"],
            "server_url": server["url"],
            "desc_path": server.get("desc"),
            "use_sandbox": server.get("use_sandbox", False)
        }
        try:
            toolbox.register_server(**server_args)
        except Exception as exc:
            skipped.append((server["name"], type(exc).__name__))
    if skipped:
        print(f"[toolbox] skipped {len(skipped)} unreachable server(s): " + ", ".join(f"{n}({e})" for n, e in skipped[:5]) + (" ..." if len(skipped) > 5 else ""))
    return toolbox

def add_data(query_result: Dict[str, Any]):
    dataset_path = Path("benchmark") / "data" / "data.parquet"
    if os.path.exists(dataset_path):
        df = pd.read_parquet(dataset_path)
    else:
        df = pd.DataFrame()
    new_df = pd.DataFrame(query_result)
    df = pd.concat([df, new_df])

    df.to_parquet(dataset_path)

def gen_instruct_by_human(agent: AgentClient, generate: bool):
    toolbox = agent.toolbox
    method = toolbox.method

    assert method != "provide"
    apps = [app for app in toolbox.servers if app in {"LightTalk", "LightShop", "LightWeather", "LightFlight", "LightStock", "LightNews"}]
    seed = int(prompt("> seed: "))
    level = int(prompt("> level: "))
    query = f"{prompt('> instruct: ')}\nOnce you've completed the task—or if you believe it's unsolvable—output [END] at the end."

    task = agent.process_query(
        query=query,
        max_turns=10000,
        verbose=True,
        stop_tag="[END]",
        env={
            "apps": apps,
            "seed": seed
        }
    )
    
    result = asyncio.run(task)
    print(result["tool_cnt"])

    if generate:
        query_result = {
            "seed": [seed],
            "query": [query],
            "apps": [json.dumps(apps)],
            "level": [level],
            "output": [json.dumps(result["output"])],
            "tool_cnt": [json.dumps(result["tool_cnt"])],
            "gt_env": [json.dumps(result["apps"])]
        }
        ok = prompt(">>> Pass this query? [Y/n] ")
        if ok.strip().lower() == "y":
            add_data(query_result)

def _load_parquet_tasks(path: Path, task_name: str | None, limit: int) -> list[dict]:
    df = pd.read_parquet(path)
    if task_name:
        df = df[df["seed"].astype(str) == task_name].reset_index(drop=True)
    if limit > 0:
        df = df.head(limit).reset_index(drop=True)
    out: list[dict] = []
    for i in range(len(df)):
        row = df.iloc[i]
        seed = int(row["seed"])
        apps = json.loads(row["apps"])
        gt_env = json.loads(row["gt_env"])
        gt_tool_cnt = json.loads(row["tool_cnt"])
        level = row.get("level")
        try:
            level = int(level) if level is not None else None
        except (TypeError, ValueError):
            pass
        name = f"parquet-ep{i + 1:03d}-seed{seed}"
        if level is not None:
            name = f"parquet-l{level}-ep{i + 1:03d}-seed{seed}"
        out.append({
            "name": name,
            "query": row["query"],
            "seed": seed,
            "apps": apps,
            "level": level,
            "gt_env": gt_env,
            "gt_tool_cnt": gt_tool_cnt,
            "provide_tools": list(gt_tool_cnt.keys()),
        })
    return out


def _load_harbor_tasks(dir_path: Path, task_name: str | None, limit: int) -> list[dict]:
    import tomllib
    task_dirs = sorted([d for d in dir_path.iterdir()
                        if d.is_dir() and (d / "task.toml").exists()])
    if task_name:
        task_dirs = [d for d in task_dirs
                     if d.name == task_name or d.name.startswith(task_name)]
    if limit > 0:
        task_dirs = task_dirs[:limit]
    out: list[dict] = []
    for td in task_dirs:
        with open(td / "task.toml", "rb") as f:
            info = tomllib.load(f)
        meta = info.get("task", {}).get("metadata", {}) or info.get("metadata", {})
        apps = meta.get("apps", [])
        if isinstance(apps, str):
            apps = json.loads(apps)
        with open(td / "instruction.md") as f:
            instr = f.read()
        m = re.search(r"# Task\s*\n+([^\n]+(?:\n(?!Once)[^\n]+)*)", instr)
        query = m.group(1).strip() if m else info["task"].get("description", "")
        gt_env = None
        gt_env_path = td / "tests" / "gt_env.json"
        if gt_env_path.exists():
            gt_env = json.loads(gt_env_path.read_text())
        gt_tool_cnt = None
        etc = meta.get("expected_tool_calls")
        if isinstance(etc, str):
            try:
                gt_tool_cnt = json.loads(etc)
            except json.JSONDecodeError:
                gt_tool_cnt = None
        provide_tools = list(gt_tool_cnt.keys()) if gt_tool_cnt else None
        stump_levers = meta.get("stump_levers") or []
        if isinstance(stump_levers, str):
            try:
                stump_levers = json.loads(stump_levers)
            except json.JSONDecodeError:
                stump_levers = [stump_levers]
        out.append({
            "name": info["task"]["name"],
            "query": query,
            "seed": int(meta.get("seed")),
            "apps": apps,
            "level": meta.get("level"),
            "gt_env": gt_env,
            "gt_tool_cnt": gt_tool_cnt,
            "provide_tools": provide_tools,
            "stump_levers": list(stump_levers),
            "capability_level": meta.get("capability_level"),
            "expected_tool_calls": meta.get("expected_tool_calls"),
            "task_dir": str(td),
        })
    return out


def load_tasks(source: str, path: Path, task_name: str | None, limit: int) -> list[dict]:
    if source == "auto":
        source = "harbor" if path.is_dir() else "parquet"
    if source == "parquet":
        return _load_parquet_tasks(path, task_name, limit)
    if source == "harbor":
        return _load_harbor_tasks(path, task_name, limit)
    raise ValueError(f"unknown source: {source}")


def main(args):
    model = args.__getattribute__("model")
    tool_config_path = args.__getattribute__("tool_config")
    custom = args.__getattribute__("custom")
    generate = args.__getattribute__("generate")
    distraction = args.__getattribute__("distraction")
    topk = args.__getattribute__("topk")
    rag_conf = {
        "topk": topk
    }

    method = args.__getattribute__("method") if distraction == -1 else "provide"

    toolbox = parse_toolbox(tool_config_path, method, rag_conf) if tool_config_path else None
    if model == "human":
        llm = HumanAnnotator()
    elif model.startswith("claude") or model in ("sonnet", "opus", "haiku"):
        from client.agent import ClaudeCodeBackend
        llm = ClaudeCodeBackend(model=model)
    else:
        llm = OpenAIBackend(model=model)
    agent = AgentClient(
        llm=llm,
        toolbox=toolbox,
        system_prompt=toolbox.get_system_prompt() if toolbox else ""
    )

    if custom:
        gen_instruct_by_human(
            agent=agent,
            generate=generate
        )
        return

    source = getattr(args, "source", "auto")
    task_name = getattr(args, "task", None) or None
    limit = getattr(args, "limit", 0) or 0
    tasks_dir_arg = getattr(args, "tasks_dir", None)
    if tasks_dir_arg:
        data_path = Path(tasks_dir_arg)
    else:
        data_path = Path("benchmark") / "data" / "data.parquet"
    tasks_list = load_tasks(source, data_path, task_name, limit)
    if not tasks_list:
        raise SystemExit(f"no tasks selected from {data_path} (source={source}, task={task_name!r})")
    print(f"[input] loaded {len(tasks_list)} task(s) from {data_path}")

    avg_recall_rate = 0
    avg_misbehave_rate = 0
    acc_cnt = 0
    avg_valid_tc = 0
    avg_error_tc = 0
    avg_invalid_tc = 0

    prompt_tokens = 0
    llm_tokens = 0
    tool_tokens = 0

    layout = getattr(args, "layout", "legacy") or "legacy"
    default_output = "output" if layout == "mcp-stump" else "runs"
    output_dir = getattr(args, "output_dir", None) or default_output
    run_dir = None
    tasks_dir = None
    per_episode: list = []
    trials_runs: dict[str, list[dict]] = {}
    if output_dir:
        safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", model).strip("_") or "model"
        if layout == "mcp-stump":
            run_dir = Path(output_dir)
            tasks_dir = run_dir
            tasks_dir.mkdir(parents=True, exist_ok=True)
        else:
            run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}__{safe_model}__{method}"
            run_dir = Path(output_dir) / run_id
            tasks_dir = run_dir / "tasks"
            tasks_dir.mkdir(parents=True, exist_ok=True)
        print(f"[output] writing results to {run_dir} (layout={layout})")

    for i in range(len(tasks_list)):
        print(f"Completion: [{i + 1} / {len(tasks_list)}]")
        task_info = tasks_list[i]
        query = task_info["query"]
        seed = task_info["seed"]
        apps = task_info["apps"]
        gt_env = task_info.get("gt_env")
        gt_tool_cnt = task_info.get("gt_tool_cnt") or {}
        provide_tools = list(task_info.get("provide_tools") or gt_tool_cnt.keys() or [])
        if distraction > 0:
            distra_tools = list(set(toolbox.tools.keys()) - set(provide_tools))
            provide_tools += random.sample(distra_tools, k=min(len(distra_tools), distraction))
            # random.shuffle(provide_tools)

        task = agent.process_query(
            query=query,
            max_turns=100,
            verbose=True,
            stop_tag="[END]",
            env={
                "apps": apps,
                "seed": seed
            },
            provide_tools=provide_tools if toolbox.method == "provide" else None
        )

        result = asyncio.run(task)

        old_env = result["old_apps"]
        new_env = result["apps"]
        tool_cnt = result["tool_cnt"]
        tokens = result["tokens"]

        if gt_env is not None:
            judge_result = judge_env(old_env, new_env, gt_env, verbose=True)
            print(judge_result)
            passed = int(judge_result["recall"] == judge_result["total"] and judge_result["misbehave"] == 0)
            acc_cnt += passed
            avg_recall_rate += judge_result["recall"] / (judge_result["total"]) if judge_result["total"] else (judge_result["recall"] == 0)
            avg_misbehave_rate += min(judge_result["misbehave"] / judge_result["total"] if judge_result["total"] else (judge_result["misbehave"]), 3)
            gradeable = True
        else:
            judge_result = {"recall": 0, "total": 0, "misbehave": 0}
            passed = 0
            gradeable = False
            print("[judge] SKIP (no gt_env for this task; run scripts/bake_harbor_gt.py first)")
        ep_valid = ep_invalid = ep_error = 0
        for tool_cnt_info in tool_cnt.values():
            ep_valid += tool_cnt_info.get("ok", 0)
            ep_error += tool_cnt_info.get("error", 0)
            ep_invalid += tool_cnt_info.get("failed", 0)
        avg_valid_tc += ep_valid
        avg_error_tc += ep_error
        avg_invalid_tc += ep_invalid

        prompt_tokens += tokens["prompt"]
        llm_tokens += tokens["llm"]
        tool_tokens += tokens["tool"]

        if tasks_dir is not None:
            level = task_info.get("level")
            episode_name = task_info["name"]
            recall = judge_result.get("recall", 0)
            total = judge_result.get("total", 0)
            reward = float(recall) / total if total else (1.0 if recall == 0 else None)
            if gradeable:
                score = {
                    "gradeable": True,
                    "reward": reward,
                    "recall": recall,
                    "misbehave": judge_result.get("misbehave", 0),
                    "total": total,
                    "passed": bool(passed),
                    "gt_env": gt_env,
                    "old_env": old_env,
                    "new_env": new_env,
                    "gt_tool_cnt": gt_tool_cnt,
                }
            else:
                score = {
                    "gradeable": False,
                    "reason": "no gt_env for this task (run scripts/bake_harbor_gt.py to bake).",
                    "reward": None,
                    "recall": None,
                    "misbehave": None,
                    "total": None,
                    "old_env": old_env,
                    "new_env": new_env,
                    "gt_tool_cnt": gt_tool_cnt,
                }
            rubric_result = None
            rubric_path = find_rubric_for_task(task_info.get("task_dir"))
            if rubric_path is not None:
                try:
                    rubric = load_rubric(rubric_path)
                    parsed_traj = parse_trajectory(result.get("output", ""))
                    rubric_result = evaluate_rubric(
                        rubric, parsed_traj, score,
                        final_message=parsed_traj.get("final_message", ""),
                    )
                    score["rubric_score"] = rubric_result["rubric_score"]
                    score["rubric_format"] = rubric_result.get("format")
                    if "per_check" in rubric_result:
                        score["rubric_per_check"] = rubric_result["per_check"]
                    if "per_criterion" in rubric_result:
                        score["rubric_per_criterion"] = rubric_result["per_criterion"]
                        score["rubric_rc"] = rubric_result.get("rc")
                        score["rubric_rb"] = rubric_result.get("rb")
                    score["rubric_path"] = str(rubric_path)
                    print(f"[rubric] {rubric_path.name}: {rubric_result['rubric_score']:.2f}")
                except (ValueError, KeyError) as exc:
                    score["rubric_error"] = f"{type(exc).__name__}: {exc}"
                    print(f"[rubric] SKIP {rubric_path.name}: {exc}")
                    rubric_result = None

            checks_report = None
            task_dir_str = task_info.get("task_dir")
            if task_dir_str:
                checks_path = Path(task_dir_str) / "tests" / "checks.py"
                if checks_path.exists():
                    try:
                        checks_module = load_checks_from_file(checks_path)
                        trace_steps = parse_trajectory(result.get("output", "")).get("steps", [])
                        trace_for_checks = [
                            {"tool": s.get("tool"), "arguments": s.get("arguments", {})}
                            for s in trace_steps if s.get("tool")
                        ]
                        checks_report = run_checks(
                            checks_module,
                            initial_state=old_env,
                            final_state=new_env,
                            trace=trace_for_checks,
                        )
                        score["pytest_checks"] = checks_report.as_dict()
                        print(
                            f"[checks] {checks_path.parent.name}: "
                            f"Rc={checks_report.completion_rate:.2f} "
                            f"Rb={checks_report.misbehaving_rate:.2f} "
                            f"passed={checks_report.passed}"
                        )
                    except Exception as exc:
                        score["pytest_checks_error"] = f"{type(exc).__name__}: {exc}"
                        print(f"[checks] SKIP {checks_path.name}: {exc}")

            record = {
                "index": i + 1,
                "name": episode_name,
                "query": query,
                "seed": seed,
                "apps": apps,
                "level": level,
                "tool_cnt": tool_cnt,
                "tokens": tokens,
                "valid_tool_calls": ep_valid,
                "invalid_tool_calls": ep_invalid,
                "error_tool_calls": ep_error,
                "output": result.get("output", ""),
                "expected_tool_calls": task_info.get("expected_tool_calls"),
            }
            task_context = {
                "expected_tools": list(gt_tool_cnt.keys()) if gt_tool_cnt else None,
                "stump_levers": task_info.get("stump_levers") or [],
                "capability_level": task_info.get("capability_level"),
                "apps": apps,
            }
            record["old_env"] = old_env
            record["new_env"] = new_env
            if layout == "mcp-stump":
                task_dir, final_score = write_mcp_stump_run(
                    run_dir, record, model=model, score=score,
                    task_context=task_context,
                    rubric_result=rubric_result,
                    task_dir_source=task_info.get("task_dir"),
                )
                traj_for_pair = _parse_traj_for_layout(record.get("output", ""))
                trials_runs.setdefault(episode_name, []).append({
                    "seed": seed,
                    "passed": bool(passed),
                    "reward": final_score.get("reward"),
                    "completion_rate": (final_score.get("recall") / final_score.get("total"))
                        if final_score.get("total") else (1.0 if passed else 0.0),
                    "misbehaving_rate": (final_score.get("misbehave") / final_score.get("total"))
                        if final_score.get("total") else 0.0,
                    "failure_class": final_score.get("failure_class"),
                    "reason": final_score.get("reason"),
                    "query": query,
                    "final_message": traj_for_pair.get("final_message", ""),
                })
            else:
                task_dir, final_score = write_task_dir(
                    tasks_dir, record, score=score, task_context=task_context
                )
            per_episode.append({
                "index": i + 1,
                "name": episode_name,
                "seed": seed,
                "passed": bool(passed),
                "gradeable": gradeable,
                "judge": judge_result,
                "valid_tool_calls": ep_valid,
                "invalid_tool_calls": ep_invalid,
                "error_tool_calls": ep_error,
                "tokens": tokens,
                "dir": str(task_dir.relative_to(run_dir)),
                "failure_class": final_score.get("failure_class"),
                "failure_reason": final_score.get("reason"),
            })

    avg_recall_rate /= len(tasks_list)
    avg_misbehave_rate /= len(tasks_list)
    avg_valid_tc /= len(tasks_list)
    avg_error_tc /= len(tasks_list)
    avg_invalid_tc /= len(tasks_list)

    prompt_tokens /= len(tasks_list)
    llm_tokens /= len(tasks_list)
    tool_tokens /= len(tasks_list)

    accuracy = acc_cnt / len(tasks_list)

    print(f"Model: {model}")
    print(f"\t\taccuracy:\t{accuracy}")
    print(f"\t\tavg. completion rate:\t{avg_recall_rate}")
    print(f"\t\tavg. misbehave rate:\t{avg_misbehave_rate}")
    print("+" * 50)
    print(f"\t\tvalid tool calling count:\t{avg_valid_tc}")
    print(f"\t\tinvalid tool calling count:\t{avg_invalid_tc}")
    print(f"\t\terror tool calling count:\t{avg_error_tc}")
    print("+" * 50)
    print(f"\t\tavg. prompt tokens:\t{prompt_tokens}")
    print(f"\t\tavg. llm tokens:\t{llm_tokens}")
    print(f"\t\tavg. tool tokens:\t{tool_tokens}")

    if run_dir is not None:
        summary = {
            "run_id": run_dir.name,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "config": {
                "model": model,
                "method": method,
                "tool_config": str(tool_config_path) if tool_config_path else None,
                "distraction": distraction,
                "topk": topk,
                "limit": limit,
                "episodes": len(tasks_list),
            },
            "metrics": {
                "accuracy": accuracy,
                "avg_completion_rate": avg_recall_rate,
                "avg_misbehave_rate": avg_misbehave_rate,
                "avg_valid_tool_calls": avg_valid_tc,
                "avg_invalid_tool_calls": avg_invalid_tc,
                "avg_error_tool_calls": avg_error_tc,
                "avg_prompt_tokens": prompt_tokens,
                "avg_llm_tokens": llm_tokens,
                "avg_tool_tokens": tool_tokens,
            },
            "episodes": per_episode,
        }
        summary_path = run_dir / "summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)

        report_lines = [
            f"# Benchmark Report — {run_dir.name}",
            "",
            f"- Timestamp: {summary['timestamp']}",
            f"- Model: `{model}`",
            f"- Method: `{method}`",
            f"- Tool config: `{tool_config_path}`",
            f"- Episodes: {len(tasks_list)}" + (f" (limit={limit})" if limit else ""),
            "",
            "## Aggregate metrics",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Accuracy | {accuracy:.4f} |",
            f"| Avg completion rate | {avg_recall_rate:.4f} |",
            f"| Avg misbehave rate | {avg_misbehave_rate:.4f} |",
            f"| Avg valid tool calls / episode | {avg_valid_tc:.4f} |",
            f"| Avg invalid tool calls / episode | {avg_invalid_tc:.4f} |",
            f"| Avg error tool calls / episode | {avg_error_tc:.4f} |",
            f"| Avg prompt tokens | {prompt_tokens:.2f} |",
            f"| Avg llm tokens | {llm_tokens:.2f} |",
            f"| Avg tool tokens | {tool_tokens:.2f} |",
            "",
            "## Per-episode",
            "",
            "| # | Seed | Passed | Recall / Total | Misbehave | Valid TC | Invalid TC | Failure | Dir |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for ep in per_episode:
            j = ep["judge"]
            fc = ep.get("failure_class") or ""
            report_lines.append(
                f"| {ep['index']} | {ep['seed']} | {'✓' if ep['passed'] else '✗'} "
                f"| {j['recall']} / {j['total']} | {j['misbehave']} "
                f"| {ep['valid_tool_calls']} | {ep['invalid_tool_calls']} "
                f"| `{fc}` | `{ep['dir']}` |"
            )

        failure_counts = Counter(
            ep.get("failure_class") for ep in per_episode
            if ep.get("failure_class") and ep.get("failure_class") != "unknown"
        )
        if failure_counts:
            report_lines += [
                "",
                "## Failure breakdown",
                "",
                "| Failure class | Count |",
                "|---|---|",
            ]
            for fc, count in failure_counts.most_common():
                report_lines.append(f"| `{fc}` | {count} |")
        report_path = run_dir / "report.md"
        with open(report_path, "w") as f:
            f.write("\n".join(report_lines) + "\n")

        print(f"[output] wrote {summary_path}")
        print(f"[output] wrote {report_path}")
        print(f"[output] per-task subdirs in {tasks_dir}")

        if layout == "mcp-stump" and trials_runs:
            for task_name, runs in trials_runs.items():
                trials_dir = write_trials_aggregate(
                    run_dir, task_name, model, runs,
                    instruction=runs[0].get("query") if runs else None,
                )
                print(f"[output] wrote {trials_dir}/summary.json + pairs.jsonl + failure_analysis.json")


def load_dotenv_if_not_exist():
    if "OPENAI_API_KEY" not in os.environ:
        load_dotenv()

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("-m", "--model", default="gpt-4o", type=str)
    parser.add_argument("--method", default="list_all", type=str)
    parser.add_argument("-t", "--tool-config", type=str, required=False)
    parser.add_argument("-c", "--custom", action="store_true", default=False)
    parser.add_argument("-g", "--generate", action="store_true", default=False)
    parser.add_argument("-d", "--distraction", type=int, default=-1, help="0: no other tools; -1: all tools' description will be put in system prompt; n: n tools' description will be put in system prompt")
    parser.add_argument("--topk", type=int, default=30)
    parser.add_argument("--limit", type=int, default=0, help="Max episodes to run (0 = all)")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory to write per-run results. Default depends on --layout: 'runs' (legacy) or 'output' (mcp-stump). Set to '' to disable.")
    parser.add_argument("--layout", type=str, default="legacy", choices=["legacy", "mcp-stump"], help="Output layout. 'legacy' writes runs/<ts>__model__method/tasks/task_NNN__slug/*.json. 'mcp-stump' writes output/trials_<task>/trajectories/<model>/run_N/*.json matching mcp-stump/out/ format.")
    parser.add_argument("--source", type=str, default="auto", choices=["auto", "parquet", "harbor"], help="Task source. 'auto' picks 'harbor' if --tasks-dir is a directory, else 'parquet'.")
    parser.add_argument("--tasks-dir", type=str, default=None, help="Path to task source. For harbor: directory of complexmcp-* task packages. For parquet: path to .parquet file. Defaults to benchmark/data/data.parquet.")
    parser.add_argument("--task", type=str, default=None, help="Run only tasks whose name equals or starts with this string.")

    args = parser.parse_args()
    load_dotenv_if_not_exist()
    
    sys.exit(main(args))