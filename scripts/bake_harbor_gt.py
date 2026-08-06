#!/usr/bin/env python3
from __future__ import annotations

import argparse
import argparse as _ap
import asyncio
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml
from dotenv import load_dotenv

from client.agent import AgentClient, ChatBackend, Toolbox
from client.rag import ChromaRAG

load_dotenv()

DEFAULT_CONFIG = _REPO_ROOT / "config" / "general.yaml"
DEFAULT_TASKS_DIR = _REPO_ROOT / "benchmark" / "harbor_final_all"


def _fake_resp(content: str) -> _ap.Namespace:
    return _ap.Namespace(
        usage=_ap.Namespace(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        choices=[_ap.Namespace(
            message=_ap.Namespace(content=content),
            finish_reason="stop",
        )],
    )


class ReplayBackend(ChatBackend):
    def __init__(self, trajectory: list[dict], end_tag: str = "[END]"):
        super().__init__()
        self.steps = list(trajectory)
        self.idx = 0
        self.end_tag = end_tag

    async def chat(self, *_args, **_kwargs):
        if self.idx >= len(self.steps):
            return _fake_resp(f"All planned tool calls executed. {self.end_tag}")
        step = self.steps[self.idx]
        self.idx += 1
        payload = json.dumps({"name": step["tool"], "arguments": step.get("args", {})})
        return _fake_resp(f"<tool>\n{payload}\n</tool>")


class EndBackend(ChatBackend):
    async def chat(self, *_args, **_kwargs):
        return _fake_resp("[END]")


def load_task(task_dir: Path) -> dict:
    with open(task_dir / "task.toml", "rb") as f:
        td = tomllib.load(f)
    meta = td["task"].get("metadata", {})
    apps = meta.get("apps", [])
    if isinstance(apps, str):
        apps = json.loads(apps)
    with open(task_dir / "instruction.md") as f:
        instr = f.read()
    m = re.search(r"# Task\s*\n+([^\n]+(?:\n(?!Once)[^\n]+)*)", instr)
    query = m.group(1).strip() if m else td["task"].get("description", "")
    trajectory_path = task_dir / "solution" / "trajectory.json"
    trajectory = []
    if trajectory_path.exists():
        with open(trajectory_path) as f:
            trajectory = json.load(f)
    return {
        "name": td["task"]["name"],
        "query": query,
        "seed": int(meta.get("seed")),
        "apps": apps,
        "trajectory": trajectory,
    }


def build_toolbox(config_path: Path) -> Toolbox:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    tb = Toolbox(rag_cls=ChromaRAG, method="rag", default_k=30)
    for entry in cfg["servers"]:
        if not entry.get("use"):
            continue
        tb.register_server(
            server_name=entry["name"],
            server_url=entry["url"],
            desc_path=entry.get("desc"),
            use_sandbox=bool(entry.get("use_sandbox")),
        )
    return tb


async def snapshot_env(tb: Toolbox, task: dict, backend: ChatBackend) -> dict[str, Any]:
    agent = AgentClient(llm=backend, toolbox=tb, system_prompt="")
    result = await agent.process_query(
        query=task["query"],
        max_turns=max(len(task["trajectory"]) + 5, 10),
        verbose=False,
        stop_tag="[END]",
        env={"apps": task["apps"], "seed": task["seed"]},
        provide_tools=None,
    )
    return result


async def bake_one(tb: Toolbox, task_dir: Path, force: bool = False) -> str:
    task = load_task(task_dir)
    tests_dir = task_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    old_env_path = tests_dir / "old_env.json"
    gt_env_path = tests_dir / "gt_env.json"

    if not force and old_env_path.exists() and gt_env_path.exists():
        return "SKIP-existing"

    if not task["trajectory"]:
        return "SKIP-no-trajectory"

    old_result = await snapshot_env(tb, task, EndBackend())
    old_env = old_result.get("apps", {})
    old_env_path.write_text(json.dumps(old_env, indent=2, default=str))

    gt_result = await snapshot_env(tb, task, ReplayBackend(task["trajectory"]))
    gt_env = gt_result.get("apps", {})
    gt_env_path.write_text(json.dumps(gt_env, indent=2, default=str))

    return f"OK-tools={sum(sum(v.values()) for v in gt_result.get('tool_cnt', {}).values())}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-t", "--tool-config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR)
    ap.add_argument("--task", type=str, default=None,
                    help="Bake only tasks whose dir name equals or starts with this string.")
    ap.add_argument("--force", action="store_true",
                    help="Re-bake even if gt_env.json + old_env.json already exist.")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    task_dirs = sorted([d for d in args.tasks_dir.iterdir()
                        if d.is_dir() and d.name.startswith("complexmcp")])
    if args.task:
        task_dirs = [d for d in task_dirs
                     if d.name == args.task or d.name.startswith(args.task)]
    if args.limit > 0:
        task_dirs = task_dirs[:args.limit]
    if not task_dirs:
        raise SystemExit("no tasks selected")

    print(f"[bake] loading toolbox from {args.tool_config}")
    tb = build_toolbox(args.tool_config)

    print(f"[bake] baking GT for {len(task_dirs)} task(s)")
    ok = skip = err = 0
    for i, td in enumerate(task_dirs, 1):
        try:
            status = asyncio.run(bake_one(tb, td, force=args.force))
            print(f"[{i}/{len(task_dirs)}] {status:30}  {td.name}")
            if status.startswith("OK"):
                ok += 1
            elif status.startswith("SKIP"):
                skip += 1
        except Exception as exc:
            err += 1
            print(f"[{i}/{len(task_dirs)}] ERROR: {type(exc).__name__}: {exc}  {td.name}")
    print(f"[bake] done: ok={ok} skip={skip} err={err}")


if __name__ == "__main__":
    main()
