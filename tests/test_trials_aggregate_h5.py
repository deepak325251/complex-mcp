"""H5: an unrecorded run_N dir on disk must be folded into n, not dropped."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from scripts.task_writer import write_trials_aggregate


def test_unrecorded_run_folded_in(tmp_path):
    traj = tmp_path / "trajectories" / "m"
    (traj / "run_1").mkdir(parents=True)   # hard-bounced, no record
    (traj / "run_2").mkdir(parents=True)
    records = [{"attempt": 2, "passed": False, "failure_class": "partial_completion"}]

    # Without trajectory_root: legacy behavior, n == 1 (run_1 invisible).
    p = write_trials_aggregate(tmp_path, "t/x", "m", records)
    assert json.loads((p / "summary.json").read_text())["metrics"]["n"] == 1

    # With trajectory_root: run_1 is reconciled in -> n == 2, taxonomy shows it.
    p = write_trials_aggregate(tmp_path, "t/x", "m", records, trajectory_root=traj)
    s = json.loads((p / "summary.json").read_text())
    assert s["metrics"]["n"] == 2
    assert "unrecorded_run" in s["metrics"]["failure_breakdown"]
