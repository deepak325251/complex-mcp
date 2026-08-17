"""Flatten a Harbor-layout job dir into `logs/` for grep and archiving.

The canonical files stay where they are; this is a mirror, one directory deep,
with job-level files prefixed `job-` and each trial's files under a directory
named for the trial. That is the shape documented by the reference layout's own
`logs/INDEX.md`.

`INDEX.md` is generated from what was ACTUALLY written, with real byte sizes --
never from a fixed list. The reference tree's INDEX.md advertises seven
job-level files and a full per-trial subdirectory while shipping only five files
and no subdirectory at all; an index that lists absent files is worse than no
index, because it reads as evidence they were produced.

Usage:
    python -m scripts.aggregate_logs output/<task-slug>
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

# (source relative to the job dir, name inside logs/)
# Job-level JSON is NOT mirrored: config/lock/result/pass_summary already sit at
# the job root, so copying them here only doubled every delivered trajectory.
# Logs proper (job.log/wrapper.log/finalize.log) are mirrored when they exist --
# they have no canonical home elsewhere.
JOB_FILES = [
    ("job.log", "job.log"),
    ("wrapper.log", "wrapper.log"),
    ("finalize.log", "finalize.log"),
]

# (source relative to a Run dir, name inside logs/<trial>/)
# Only files with no canonical duplicate under trajectory/Run N/. report.json,
# result.json, trial-config.json and the reward JSONs were straight copies.
TRIAL_FILES = [
    ("judge_response.txt", "judge-response.txt"),
    ("verifier/ctrf.json", "verifier-ctrf.json"),
    ("verifier/reward.txt", "verifier-reward.txt"),
    ("verifier/test-stdout.txt", "verifier-stdout.txt"),
    ("agent/complexmcp.txt", "agent-stream.txt"),
    ("trial.log", "trial.log"),
]


def _copy(src: Path, dest: Path) -> int | None:
    """Copy if present; return the byte size, or None when absent."""
    if not src.is_file():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest.stat().st_size


def _run_sort_key(p: Path):
    """`Run_10` must sort after `Run_9`, not between `Run_1` and `Run_2`."""
    tail = p.name.replace(" ", "_").rsplit("_", 1)[-1]
    return (0, int(tail)) if tail.isdigit() else (1, 0)


def aggregate(job_dir: str | Path) -> Path:
    """Write each run's logs INSIDE its own run directory.

    They used to live at `logs/<trial_name>/` at the job root, but `trial_name`
    is derived from the task digest and is therefore identical for every attempt
    -- so a 2-attempt run produced ONE mirror and Run_2 silently overwrote
    Run_1's agent stream. Keying on the run directory instead makes collision
    impossible by construction, no matter how the trial is named.
    """
    job_dir = Path(job_dir)
    traj = job_dir / "trajectory"
    if not traj.is_dir():
        return traj

    for run_dir in sorted((d for d in traj.iterdir() if d.is_dir()),
                          key=_run_sort_key):
        logs = run_dir / "logs"
        for src_name, dest_name in TRIAL_FILES:
            _copy(run_dir / src_name, logs / dest_name)
        # Job-level logs (job.log/wrapper.log/finalize.log) have no canonical
        # home elsewhere; mirror them alongside the first run only.
        if run_dir == min(traj.iterdir(), key=_run_sort_key):
            for src_name, dest_name in JOB_FILES:
                _copy(job_dir / src_name, logs / dest_name)
        if logs.is_dir() and not any(logs.iterdir()):
            logs.rmdir()          # never leave an empty logs/ behind
    return traj




def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("job_dir", type=Path, help="a Harbor-layout job directory")
    args = ap.parse_args(argv)
    if not args.job_dir.is_dir():
        raise SystemExit(f"not a directory: {args.job_dir}")
    aggregate(args.job_dir)
    print(f"[logs] wrote per-run logs under {args.job_dir}/trajectory/Run_*/logs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
