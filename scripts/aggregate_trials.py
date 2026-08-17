#!/usr/bin/env python3
"""Post-hoc roll-up over per-task trials_*/summary.json folders.

run_benchmark.py only writes the top-level passk_summary.json from the
`trials_runs` it held *in memory* during a single invocation. When a results
directory is assembled from several separate runs (or tasks are run one at a
time and collected), that top-level file is stale -- it reflects only the last
run, not every trials_* folder on disk. This script rebuilds it by scanning the
folders, so accuracy/pass@k describe the whole merged set.

Usage:
    python scripts/aggregate_trials.py <run_dir> [--model MODEL] [--at 1,2,4]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark.passk import estimate as passk_estimate


def _load_trial(summary_path: Path) -> dict | None:
    try:
        return json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def aggregate(run_dir: Path, model: str | None, at_ks: list[int]) -> dict:
    per_task: list[dict] = []
    mode_hist: Counter = Counter()
    accuracies: list[float] = []
    all_attempts = 0

    for summary_path in sorted(run_dir.glob("trials_*/summary.json")):
        trial = _load_trial(summary_path)
        if not trial:
            print(f"[warn] skipping unreadable {summary_path}")
            continue
        if model and trial.get("model") not in (None, model):
            continue

        attempts = trial.get("attempts") or []
        n = len(attempts)
        c = sum(1 for a in attempts if a.get("passed"))
        if n == 0:
            print(f"[warn] no attempts in {summary_path}")
            continue

        est = passk_estimate(n, c, at_ks)
        per_task.append({
            "task": trial.get("task", summary_path.parent.name),
            "n": n, "c": c,
            "p_hat": est["p_hat"], "ci95": est["ci95"],
            "pass@k": est["pass@k"], "pass^k": est["pass^k"],
        })
        accuracies.append(c / n)
        all_attempts += n
        for a in attempts:
            if not a.get("passed") and a.get("failure_class"):
                mode_hist[a["failure_class"]] += 1

    all_ks = sorted({int(k) for t in per_task for k in t["pass@k"]})

    def _mean_over(field: str, k: int) -> float | None:
        vals = [t[field][str(k)] for t in per_task if str(k) in t[field]]
        return round(sum(vals) / len(vals), 6) if vals else None

    return {
        "model": model or (per_task and _first_model(run_dir)) or "unknown",
        "tasks": len(per_task),
        "total_attempts": all_attempts,
        "accuracy": round(sum(accuracies) / len(accuracies), 6) if accuracies else 0.0,
        "at": at_ks,
        "mean_pass@k": {str(k): _mean_over("pass@k", k) for k in all_ks},
        "mean_pass^k": {str(k): _mean_over("pass^k", k) for k in all_ks},
        "failure_mode_histogram": dict(mode_hist.most_common()),
        "per_task": per_task,
    }


def _first_model(run_dir: Path) -> str | None:
    for p in sorted(run_dir.glob("trials_*/summary.json")):
        t = _load_trial(p)
        if t and t.get("model"):
            return t["model"]
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--model", default=None)
    ap.add_argument("--at", default="1", help="comma-separated k values, e.g. 1,2,4")
    ap.add_argument("--write", action="store_true",
                    help="overwrite <run_dir>/passk_summary.json (default: print only)")
    args = ap.parse_args()

    at_ks = [int(x) for x in args.at.split(",") if x.strip()]
    summary = aggregate(args.run_dir, args.model, at_ks)
    text = json.dumps(summary, indent=2)
    if args.write:
        out = args.run_dir / "passk_summary.json"
        out.write_text(text)
        print(f"[output] wrote {out}")
    print(text)


if __name__ == "__main__":
    main()
