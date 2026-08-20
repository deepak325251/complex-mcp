#!/usr/bin/env python3
"""Generate tests/old_env.json (and optionally a gt_env.json skeleton) for a task.

Oracle-free authoring flow. old_env is the seeded world BEFORE the task: booting
each app in-process at the task's seed and dumping its session. This guarantees the
exact dump schema and the exact seeded ids/entities the agent's new_env is built
from -- so a hand-authored gt_env stays consistent with it.

seed + apps come from task.toml [task.metadata] (no oracle.json needed).

Usage:
    python scripts/make_old_env.py input/08-whitfield-reunion-cookout
    python scripts/make_old_env.py <task_dir> --gt      # also write gt_env.json (copy to edit)
    python scripts/make_old_env.py <task_dir> --stdout  # print, don't write

Then author gt_env.json = old_env.json with ONLY the intended fields changed.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark.bake_state_mcp import (  # noqa: E402
    boot_world, dump_world, resolve_seed, resolve_apps,
)


def make_old_env(task_dir: str, apps=None, seed=None) -> dict:
    # apps/seed overrides let a caller (run_benchmark) pass values it already
    # resolved elsewhere (e.g. apps derived from gold_plan.json when task.toml
    # declares none); otherwise both come from task.toml [task.metadata].
    seed = resolve_seed(task_dir) if seed is None else int(seed)
    apps = list(apps) if apps else resolve_apps(task_dir)
    if not apps:
        raise SystemExit(f"{task_dir}: no apps in task.toml [task.metadata].apps")
    sessions = boot_world(apps, seed)
    old = dump_world(sessions)
    print(f"[old_env] seed={seed}  apps={apps}", file=sys.stderr)
    return old


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("task_dir", help="path to the task bundle directory")
    ap.add_argument("--gt", action="store_true",
                    help="also write tests/gt_env.json as a copy of old_env to hand-edit")
    ap.add_argument("--stdout", action="store_true",
                    help="print old_env to stdout instead of writing files")
    args = ap.parse_args()

    old = make_old_env(args.task_dir)
    text = json.dumps(old, ensure_ascii=False, indent=2)

    if args.stdout:
        print(text)
        return

    tests_dir = os.path.join(args.task_dir, "tests")
    os.makedirs(tests_dir, exist_ok=True)
    old_p = os.path.join(tests_dir, "old_env.json")
    with open(old_p, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {old_p}", file=sys.stderr)

    if args.gt:
        gt_p = os.path.join(tests_dir, "gt_env.json")
        if os.path.exists(gt_p):
            print(f"skip {gt_p} (already exists — not overwriting)", file=sys.stderr)
        else:
            with open(gt_p, "w", encoding="utf-8") as f:
                f.write(text)  # identical to old_env; edit the target fields by hand
            print(f"wrote {gt_p}  (copy of old_env — now edit only the changed fields)",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
