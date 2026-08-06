from client.agent import OpenAIBackend, HumanAnnotator, AgentClient, Toolbox
from client.rag import ChromaRAG
from benchmark.judge import judge_env
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
from datetime import datetime

import pandas as pd
from shortuuid import uuid

def parse_toolbox(tool_config_path: str | Path, method: str, rag_conf: Dict = {}):
    config = {}
    with open(tool_config_path) as f:
        data = yaml.safe_load(f)
        config["servers"] = data["servers"]

    toolbox = Toolbox(method=method) if method not in ["rag", "fetch"] else Toolbox(method=method, rag_cls=ChromaRAG, default_k=rag_conf["topk"])
    for server in config["servers"]:
        if not server["use"]: continue
        server_args = {
            "server_name": server["name"],
            "server_url": server["url"],
            "desc_path": server.get("desc"),
            "use_sandbox": server.get("use_sandbox", False)
        }
        toolbox.register_server(**server_args)
    
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

    data_path = Path("benchmark") / "data" / "data.parquet"
    dataset = pd.read_parquet(data_path)
    limit = getattr(args, "limit", 0) or 0
    if limit > 0:
        dataset = dataset.head(limit).reset_index(drop=True)

    avg_recall_rate = 0
    avg_misbehave_rate = 0
    acc_cnt = 0
    avg_valid_tc = 0
    avg_error_tc = 0
    avg_invalid_tc = 0

    prompt_tokens = 0
    llm_tokens = 0
    tool_tokens = 0

    output_dir = getattr(args, "output_dir", "runs") or ""
    run_dir = None
    episodes_dir = None
    per_episode: list = []
    if output_dir:
        safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", model).strip("_") or "model"
        run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}__{safe_model}__{method}"
        run_dir = Path(output_dir) / run_id
        episodes_dir = run_dir / "episodes"
        episodes_dir.mkdir(parents=True, exist_ok=True)
        print(f"[output] writing results to {run_dir}")

    for i in range(len(dataset)):
        print(f"Completion: [{i + 1} / {len(dataset)}]")
        data = dataset.iloc[i]
        query = data["query"]
        seed = int(data["seed"])
        apps = json.loads(data["apps"])
        gt_env = json.loads(data["gt_env"])
        gt_tool_cnt = json.loads(data["tool_cnt"])
        provide_tools = list(gt_tool_cnt.keys())
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

        judge_result = judge_env(old_env, new_env, gt_env, verbose=True)
        print(judge_result)
        passed = int(judge_result["recall"] == judge_result["total"] and judge_result["misbehave"] == 0)
        acc_cnt += passed
        avg_recall_rate += judge_result["recall"] / (judge_result["total"]) if judge_result["total"] else (judge_result["recall"] == 0)
        avg_misbehave_rate += min(judge_result["misbehave"] / judge_result["total"] if judge_result["total"] else (judge_result["misbehave"]), 3)
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

        if episodes_dir is not None:
            episode_record = {
                "index": i + 1,
                "seed": seed,
                "query": query,
                "apps": apps,
                "provide_tools": provide_tools,
                "gt_env": gt_env,
                "old_env": old_env,
                "new_env": new_env,
                "gt_tool_cnt": gt_tool_cnt,
                "tool_cnt": tool_cnt,
                "tokens": tokens,
                "judge": judge_result,
                "passed": bool(passed),
                "output": result.get("output"),
            }
            ep_path = episodes_dir / f"ep_{i + 1:03d}_seed_{seed}.json"
            with open(ep_path, "w") as f:
                json.dump(episode_record, f, indent=2, default=str)
            per_episode.append({
                "index": i + 1,
                "seed": seed,
                "passed": bool(passed),
                "judge": judge_result,
                "valid_tool_calls": ep_valid,
                "invalid_tool_calls": ep_invalid,
                "error_tool_calls": ep_error,
                "tokens": tokens,
                "file": str(ep_path.relative_to(run_dir)),
            })

    avg_recall_rate /= len(dataset)
    avg_misbehave_rate /= len(dataset)
    avg_valid_tc /= len(dataset)
    avg_error_tc /= len(dataset)
    avg_invalid_tc /= len(dataset)

    prompt_tokens /= len(dataset)
    llm_tokens /= len(dataset)
    tool_tokens /= len(dataset)

    accuracy = acc_cnt / len(dataset)

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
                "episodes": len(dataset),
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
            f"- Episodes: {len(dataset)}" + (f" (limit={limit})" if limit else ""),
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
            "| # | Seed | Passed | Recall / Total | Misbehave | Valid TC | Invalid TC | File |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for ep in per_episode:
            j = ep["judge"]
            report_lines.append(
                f"| {ep['index']} | {ep['seed']} | {'✓' if ep['passed'] else '✗'} "
                f"| {j['recall']} / {j['total']} | {j['misbehave']} "
                f"| {ep['valid_tool_calls']} | {ep['invalid_tool_calls']} | `{ep['file']}` |"
            )
        report_path = run_dir / "report.md"
        with open(report_path, "w") as f:
            f.write("\n".join(report_lines) + "\n")

        print(f"[output] wrote {summary_path}")
        print(f"[output] wrote {report_path}")
        print(f"[output] per-episode JSON in {episodes_dir}")


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
    parser.add_argument("--output-dir", type=str, default="runs", help="Directory to write per-run results (summary.json, report.md, episodes/). Set to '' to disable.")

    args = parser.parse_args()
    load_dotenv_if_not_exist()
    
    sys.exit(main(args))