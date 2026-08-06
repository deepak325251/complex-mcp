#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.task_writer import write_task_dir


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--delete-flat", action="store_true")
    args = ap.parse_args()

    tasks_dir = args.run_dir / "tasks"
    if not tasks_dir.is_dir():
        raise SystemExit(f"no tasks/ subdir under {args.run_dir}")

    flats = sorted(tasks_dir.glob("task_*.json"))
    if not flats:
        raise SystemExit(f"no task_*.json in {tasks_dir}")

    for flat in flats:
        record = json.loads(flat.read_text())
        subdir = write_task_dir(tasks_dir, record)
        print(f"[ok] {flat.name} -> {subdir.relative_to(args.run_dir)}")
        if args.delete_flat:
            flat.unlink()
            print(f"     removed {flat.name}")


if __name__ == "__main__":
    main()
