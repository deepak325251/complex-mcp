"""Per-test outcomes must reach report.json, and must agree with verifier/ctrf.json.

Regression cover for two bugs that made every weighted-grader run under-report:

  B1  `task_writer` read `score["pytest_checks"]`, a key nothing ever wrote, so
      `test_weights_percentage` was null on every run -- even one whose
      `traj_tests` component had scored 0.3333 over 8 tests.
  B2  `score["passed_tests"]` was read from `judge_result["detail"]`, but the
      weighted grader stores it under `judge_result["traj_tests"]`, so
      detail.json said no tests ran while verifier/ctrf.json listed all of them.

Both are now served by `weighted_judge.traj_test_rows`, and these tests pin the
two consumers to it.
"""

import json

from benchmark.weighted_judge import (
    load_test_weight_map,
    traj_test_rows,
    write_weighted_verifier,
)


# Shaped exactly like a real weighted judge_result (values taken from a live
# 14aug run: 8 tests, traj_tests component value 0.3333).
JUDGE_RESULT = {
    "reward": 0.230754,
    "traj_tests": {
        "recall": 2, "total": 4, "misbehave": 0,
        "passed_tests": {
            "test_world_ends_correct": False,
            "test_finance_summary_tags": True,
            "test_guard_ledger_transitioned": False,
            "test_guard_drive_edited": True,
        },
    },
    "components": {"traj_tests": {"weight": 5, "value": 0.3333, "earned": 1.6665}},
}

WEIGHTS = {
    "components": {"traj_tests": {"tests": {
        "test_world_ends_correct": 5,
        "test_finance_summary_tags": 3,
        "test_guard_ledger_transitioned": -3,
        "test_guard_drive_edited": -3,
    }}}
}


def _grading_dir(tmp_path):
    (tmp_path / "test_weights.json").write_text(json.dumps(WEIGHTS))
    return tmp_path


def test_weight_map_reads_ledger_shape(tmp_path):
    assert load_test_weight_map(_grading_dir(tmp_path))["test_world_ends_correct"] == 5


def test_weight_map_absent_file_is_empty(tmp_path):
    assert load_test_weight_map(tmp_path) == {}
    assert load_test_weight_map(None) == {}


def test_rows_carry_every_test(tmp_path):
    rows, _ = traj_test_rows(JUDGE_RESULT, _grading_dir(tmp_path))
    assert len(rows) == 4
    assert {r["name"] for r in rows} == set(WEIGHTS["components"]["traj_tests"]["tests"])


def test_guard_polarity_is_outcome_not_raw_flag(tmp_path):
    """A guard carries negative weight; `passed_tests[g] is True` means the
    forbidden thing HAPPENED, so its outcome is False. Reporting the raw flag
    scores a guard doing its job as a failure."""
    rows = {r["name"]: r for r in traj_test_rows(JUDGE_RESULT, _grading_dir(tmp_path))[0]}

    # goals: outcome == raw flag
    assert rows["test_world_ends_correct"]["passed"] is False
    assert rows["test_finance_summary_tags"]["passed"] is True
    # guards: outcome == NOT raw flag
    assert rows["test_guard_ledger_transitioned"]["passed"] is True   # did not fire
    assert rows["test_guard_drive_edited"]["passed"] is False         # fired


def test_weighted_score_is_the_ledger_value_not_a_recomputation(tmp_path):
    """report.json must quote the component value the reward actually used."""
    _, score = traj_test_rows(JUDGE_RESULT, _grading_dir(tmp_path))
    assert score == 0.3333


def test_unweighted_test_defaults_to_positive_one(tmp_path):
    result = json.loads(json.dumps(JUDGE_RESULT))
    result["traj_tests"]["passed_tests"]["test_not_in_weights"] = True
    rows = {r["name"]: r for r in traj_test_rows(result, _grading_dir(tmp_path))[0]}
    assert rows["test_not_in_weights"] == {
        "name": "test_not_in_weights", "weight": 1.0, "passed": True}


def test_rows_are_deterministically_ordered(tmp_path):
    gd = _grading_dir(tmp_path)
    assert traj_test_rows(JUDGE_RESULT, gd)[0] == traj_test_rows(JUDGE_RESULT, gd)[0]
    names = [r["name"] for r in traj_test_rows(JUDGE_RESULT, gd)[0]]
    assert names == sorted(names)


def test_ctrf_and_rows_never_disagree(tmp_path):
    """The whole point of the shared helper: verifier/ctrf.json and report.json
    are two renderings of one computation."""
    gd = _grading_dir(tmp_path)
    out = tmp_path / "run"
    out.mkdir()
    write_weighted_verifier(out, JUDGE_RESULT, gd)
    ctrf = json.loads((out / "verifier" / "ctrf.json").read_text())["results"]
    rows, _ = traj_test_rows(JUDGE_RESULT, gd)

    by_name = {t["name"]: t for t in ctrf["tests"]}
    for r in rows:
        assert by_name[r["name"]]["status"] == ("passed" if r["passed"] else "failed")
        assert by_name[r["name"]]["extra"]["weight"] == r["weight"]
    assert ctrf["summary"]["passed"] == sum(1 for r in rows if r["passed"])


def test_empty_traj_tests_yields_no_rows(tmp_path):
    rows, score = traj_test_rows({"components": {}}, _grading_dir(tmp_path))
    assert rows == []
    assert score is None
