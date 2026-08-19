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


def test_unrecorded_run_uses_real_report_when_present(tmp_path):
    """Regression: a run_N dir that actually completed and graded (report.json
    + diagnosis.json on disk) but fell out of the in-memory run_records list
    (e.g. process restarted before the aggregate was written) must be
    reconciled in with its REAL reward/failure_class, not overwritten with a
    fabricated "unrecorded_run" hard-bounce label."""
    traj = tmp_path / "trajectories" / "m"
    run_1 = traj / "run_1"
    run_1.mkdir(parents=True)
    (run_1 / "report.json").write_text(json.dumps({
        "attempt": 1, "passed": False, "reward": 0.365762,
        "completion_rate": 0.178571, "misbehaving_rate": 0.0, "seed": 42,
    }))
    (run_1 / "diagnosis.json").write_text(json.dumps({
        "failure_class": "environment_mismatch",
        "reason": "dirty_state lever declared but the world never surfaced a dirty collection",
    }))
    (traj / "run_2").mkdir(parents=True)
    records = [{"attempt": 2, "passed": False, "failure_class": "partial_completion"}]

    p = write_trials_aggregate(tmp_path, "t/y", "m", records, trajectory_root=traj)
    s = json.loads((p / "summary.json").read_text())
    assert s["metrics"]["n"] == 2
    assert "unrecorded_run" not in s["metrics"]["failure_breakdown"]
    assert s["metrics"]["failure_breakdown"].get("environment_mismatch") == 1
    run_1_attempt = next(a for a in s["attempts"] if a["attempt"] == 1)
    assert run_1_attempt["reward"] == 0.365762
    assert run_1_attempt["failure_class"] == "environment_mismatch"
