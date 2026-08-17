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
JOB_FILES = [
    ("config.json", "job-config.json"),
    ("lock.json", "job-lock.json"),
    ("result.json", "job-result.json"),
    ("pass_summary.json", "pass-summary.json"),
    ("passk_summary.json", "passk-summary.json"),
    ("job.log", "job.log"),
    ("wrapper.log", "wrapper.log"),
    ("finalize.log", "finalize.log"),
]

# (source relative to a Run dir, name inside logs/<trial>/)
TRIAL_FILES = [
    ("report.json", "report.json"),
    ("result.json", "result.json"),
    ("config.json", "trial-config.json"),
    ("judge_response.txt", "judge-response.txt"),
    ("artifacts/manifest.json", "artifacts-manifest.json"),
    ("verifier/ctrf.json", "verifier-ctrf.json"),
    ("verifier/reward.json", "verifier-reward.json"),
    ("verifier/reward.txt", "verifier-reward.txt"),
    ("verifier/reward_raw.json", "verifier-reward-raw.json"),
    ("verifier/reward_raw.txt", "verifier-reward-raw.txt"),
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
    """`Run 10` must sort after `Run 9`, not between `Run 1` and `Run 2`."""
    tail = p.name.rsplit(" ", 1)[-1]
    return (0, int(tail)) if tail.isdigit() else (1, 0)


def aggregate(job_dir: str | Path) -> Path:
    job_dir = Path(job_dir)
    logs = job_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    written: list[tuple[str, int]] = []
    for src_name, dest_name in JOB_FILES:
        size = _copy(job_dir / src_name, logs / dest_name)
        if size is not None:
            written.append((dest_name, size))

    trials: list[tuple[str, list[tuple[str, int]]]] = []
    traj = job_dir / "trajectory"
    if traj.is_dir():
        for run_dir in sorted((d for d in traj.iterdir() if d.is_dir()),
                              key=_run_sort_key):
            # Name the mirror directory by the trial name the trial itself
            # recorded, falling back to the run dir when it is unreadable --
            # `Run 1` contains a space, which is awkward but never wrong.
            name = _trial_name(run_dir)
            rows: list[tuple[str, int]] = []
            for src_name, dest_name in TRIAL_FILES:
                size = _copy(run_dir / src_name, logs / name / dest_name)
                if size is not None:
                    rows.append((dest_name, size))
            if rows:
                trials.append((name, rows))

    (logs / "INDEX.md").write_text(_index(job_dir.name, written, trials))
    return logs


def _trial_name(run_dir: Path) -> str:
    import json
    cfg = run_dir / "config.json"
    if cfg.is_file():
        try:
            name = json.loads(cfg.read_text()).get("trial_name")
            if name:
                return str(name)
        except (OSError, json.JSONDecodeError):
            pass
    return run_dir.name


def _index(job_label: str, job_rows, trials) -> str:
    out = [f"# Logs index for {job_label}", "",
           "Aggregated by scripts/aggregate_logs.py. Sources are the canonical",
           "files under this job dir; this tree is a flat mirror for grep and",
           "archiving. Every entry below was actually written.", "",
           "## Job-level", ""]
    out += [f"- `{n}` — {s} bytes" for n, s in job_rows] or ["- (none)"]
    out += ["", "## Trials", ""]
    if not trials:
        out.append("- (none)")
    for name, rows in trials:
        out += [f"### {name}", ""]
        out += [f"- `{name}/{n}` — {s} bytes" for n, s in rows]
        out.append("")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("job_dir", type=Path, help="a Harbor-layout job directory")
    args = ap.parse_args(argv)
    if not args.job_dir.is_dir():
        raise SystemExit(f"not a directory: {args.job_dir}")
    print(f"[logs] wrote {aggregate(args.job_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
