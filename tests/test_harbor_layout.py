"""Harbor-native layout: structure, scale, and no fabricated provenance.

The reference tree is the ground truth for every schema here. Two failure modes
this pins down because both are silent:

  * `verifier/reward.json` is a PERCENTAGE while `reward_raw.json` is the
    fraction. A missed conversion reports 0.447 as "0.447%"; a doubled one
    reports 44.74 as "4474%". Both look plausible.
  * `report.test_weights_percentage` must be the LEDGER's traj_tests value, not
    a recomputation. Recomputing it through `runreport.weighted_percentage`
    inverts guard polarity and can go negative (-9.09% on a run whose real
    score was 33.33%).
"""

import json

import pytest

from benchmark.harbor_layout import (
    PRODUCER,
    build_report,
    job_name,
    pct,
    task_digest,
    trial_name,
    write_harbor_job,
    write_harbor_trial,
    _honest_cost,
    _mean,
    _round,
)


JUDGE = {
    "reward": 0.230754,
    "passed": False,
    "rubric_score": None,
    "traj_tests": {"passed_tests": {
        "test_world_ends_correct": False,
        "test_finance_summary_tags": True,
        "test_guard_drive_edited": False,     # guard did not fire -> outcome pass
    }},
    "components": {"traj_tests": {"weight": 5, "value": 0.3333}},
}

RUBRIC = {"per_criterion": [
    {"number": "1", "criterion": "reports ledger figure", "score": 3,
     "is_positive": True, "satisfied": True, "type": "constraint_compliance",
     "evaluation_target": "final_answer", "importance": "critical"},
    {"number": "2", "criterion": "names drive unverified", "score": 2,
     "is_positive": True, "satisfied": False},
]}

RECORD = {"name": "mcp-stump/shpa-grant-close-coordination", "output": "log text",
          "usage": {"input_tokens": 1000, "output_tokens": 100,
                    "cache_read_tokens": 50, "cost_usd": 0.5}}


@pytest.fixture
def task_dir(tmp_path):
    d = tmp_path / "task"
    (d / "tests").mkdir(parents=True)
    (d / "task.toml").write_text(
        'artifacts = [{ source = "/tmp/final_state.json", service = "sandbox" }]\n'
        '[task]\nname = "mcp-stump/shpa-grant-close-coordination"\n')
    (d / "tests" / "test_weights.json").write_text(json.dumps({"components": {
        "traj_tests": {"tests": {"test_world_ends_correct": 5,
                                 "test_finance_summary_tags": 3,
                                 "test_guard_drive_edited": -3}}}}))
    return d


@pytest.fixture
def job(tmp_path, task_dir):
    jd = tmp_path / "out" / "shpa-grant-close-coordination"
    label = job_name(RECORD["name"], "220739")
    rows = [write_harbor_trial(
        jd, n, record=RECORD, model="claude-opus-4-8", judge_result=JUDGE,
        task_dir=task_dir, grading_dir=task_dir / "tests", rubric_result=RUBRIC,
        atif_doc={"schema_version": "ATIF-v1.7", "steps": []},
        job_id="job-1", job_label=label) for n in (1, 2)]
    write_harbor_job(jd, task_name=RECORD["name"], task_dir=task_dir,
                     model="claude-opus-4-8", trials=rows, job_id="job-1",
                     job_label=label, started_at="2026-08-17T10:00:00.0Z",
                     finished_at="2026-08-17T10:30:00.0Z", pass_at_k={"1": 0.0})
    return jd


# --- rounding / scale ------------------------------------------------------

def test_round_is_half_up_not_half_even():
    assert _round(46.665, 2) == 46.67        # python's round() gives 46.66
    assert _mean([33.33, 60.0]) == 46.67
    assert _mean([44.74, 75.0]) == 59.87     # the reference layout's value


@pytest.mark.parametrize("frac,expected", [
    (0.0, 0.0), (1.0, 100.0), (0.4473684210526316, 44.7368), (0.230754, 23.0754),
])
def test_pct_matches_reference(frac, expected):
    assert pct(frac) == expected


def test_pct_of_none_is_none():
    assert pct(None) is None


def test_reward_files_are_one_conversion_apart(job):
    for n in (1, 2):
        v = job / "trajectory" / f"Run {n}" / "verifier"
        raw = json.loads((v / "reward_raw.json").read_text())["reward"]
        shown = json.loads((v / "reward.json").read_text())["reward"]
        assert raw == 0.230754                 # fraction, full precision
        assert shown == pct(raw)               # percentage
        assert (v / "reward_raw.txt").read_text() == str(raw)
        assert (v / "reward.txt").read_text() == str(shown)


# --- report ----------------------------------------------------------------

def test_percentage_comes_from_the_ledger_not_a_recomputation(task_dir):
    r = build_report("m", 1, JUDGE, task_dir / "tests", RUBRIC)
    assert r["test_weights_percentage"] == 33.33      # == ledger value * 100
    assert r["pytest"]["reward"] == 0.3333


def test_guard_outcome_never_drives_the_score_negative(task_dir):
    r = build_report("m", 1, JUDGE, task_dir / "tests", RUBRIC)
    assert r["test_weights_percentage"] > 0
    guard = next(t for t in r["pytest"]["tests"] if t["weight"] < 0)
    assert guard["passed"] is True                    # did not fire == passed


def test_report_keyset_matches_reference(task_dir):
    r = build_report("m", 1, JUDGE, task_dir / "tests", RUBRIC)
    assert set(r) == {"model", "run_index", "include_multimodal", "pytest",
                      "rubric", "final_reward", "test_weights_percentage",
                      "rubric_weights_percentage"}
    assert set(r["pytest"]) == {"passed", "failed", "exit_code", "reward", "tests"}
    assert set(r["rubric"][0]) == {"number", "criterion", "type",
                                   "evaluation_target", "importance", "score",
                                   "is_positive", "passed", "justification"}


def test_input_rubric_vocabulary_passes_through_unchanged(task_dir):
    """The task input is frozen; its vocabulary must not be remapped."""
    r = build_report("m", 1, JUDGE, task_dir / "tests", RUBRIC)
    assert r["rubric"][0]["importance"] == "critical"
    assert r["rubric"][0]["evaluation_target"] == "final_answer"


def test_final_reward_is_the_mean_of_the_two_percentages(task_dir):
    r = build_report("m", 1, JUDGE, task_dir / "tests", RUBRIC)
    assert r["rubric_weights_percentage"] == 60.0     # 3 of 5
    assert r["final_reward"] == _mean([33.33, 60.0])


# --- structure -------------------------------------------------------------

def test_expected_files_exist(job):
    for rel in ("config.json", "lock.json", "result.json", "pass_summary.json",
                "trajectory/Run 1/report.json", "trajectory/Run 1/config.json",
                "trajectory/Run 1/lock.json", "trajectory/Run 1/result.json",
                "trajectory/Run 1/agent/trajectory.json",
                f"trajectory/Run 1/agent/{PRODUCER}.txt",
                "trajectory/Run 1/verifier/ctrf.json",
                "trajectory/Run 1/verifier/test-stdout.txt",
                "trajectory/Run 1/artifacts/manifest.json"):
        assert (job / rel).is_file(), rel


def test_run_dir_naming(job):
    names = sorted(p.name for p in (job / "trajectory").iterdir())
    assert names == ["Run 1", "Run 2"]      # capital R, literal space


def test_ctrf_summary_carries_scores(job):
    c = json.loads((job / "trajectory/Run 1/verifier/ctrf.json").read_text())["results"]
    assert c["summary"]["weighted_percentage"] == 33.33
    assert c["summary"]["overall_score"] == 0.3333
    assert set(c["tests"][0]) == {"name", "status", "duration"}


def test_pass_summary_shape(job):
    ps = json.loads((job / "pass_summary.json").read_text())
    assert ps["runs"] == 2
    assert ps["average_combined_score"] == _mean([33.33, 60.0])
    assert set(ps["per_run"][0]) == {"run_index", "include_multimodal",
                                     "test_weights_percentage",
                                     "rubric_weights_percentage", "combined_score"}


def test_job_result_totals_are_summed_not_sampled(job):
    r = json.loads((job / "result.json").read_text())["stats"]
    assert r["n_input_tokens"] == 2000      # two trials x 1000
    assert r["n_output_tokens"] == 200
    ev = r["evals"][f"{PRODUCER}__claude-opus-4-8__adhoc"]
    assert ev["n_trials"] == 2
    assert ev["pass_at_k"] == {"1": 0.0}


# --- no fabricated provenance ---------------------------------------------

def test_agent_is_never_claimed_to_be_claude_code(job):
    res = json.loads((job / "trajectory/Run 1/result.json").read_text())
    assert res["agent_info"]["name"] == PRODUCER != "claude-code"
    assert json.loads((job / "config.json").read_text())["agents"][0]["name"] == PRODUCER


def test_no_synthesised_claude_code_sessions(job):
    assert not (job / "trajectory/Run 1/agent/sessions").exists()
    assert not (job / "trajectory/Run 1/agent/claude-code.txt").exists()


def test_digest_is_recomputable(job, task_dir):
    lock = json.loads((job / "trajectory/Run 1/lock.json").read_text())
    assert lock["task"]["digest"] == task_digest(task_dir)
    res = json.loads((job / "trajectory/Run 1/result.json").read_text())
    assert res["task_checksum"] == task_digest(task_dir).removeprefix("sha256:")


def test_digest_changes_when_the_task_changes(task_dir):
    before = task_digest(task_dir)
    (task_dir / "tests" / "extra.json").write_text("{}")
    assert task_digest(task_dir) != before


def test_trial_name_is_deterministic(task_dir):
    d = task_digest(task_dir)
    assert trial_name(RECORD["name"], d) == trial_name(RECORD["name"], d)


def test_zero_cost_with_real_tokens_is_reported_as_unknown():
    assert _honest_cost({"cost_usd": 0.0, "output_tokens": 16070}) is None
    assert _honest_cost({"cost_usd": 4.59, "output_tokens": 16070}) == 4.59


def test_job_cost_is_none_when_any_trial_cost_is_unknown(tmp_path, task_dir):
    jd = tmp_path / "j"
    rec = dict(RECORD, usage={"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0})
    row = write_harbor_trial(jd, 1, record=rec, model="m", judge_result=JUDGE,
                             task_dir=task_dir, grading_dir=task_dir / "tests",
                             job_id="j", job_label="l")
    write_harbor_job(jd, task_name=RECORD["name"], task_dir=task_dir, model="m",
                     trials=[row], job_id="j", job_label="l",
                     started_at="a", finished_at="b")
    assert json.loads((jd / "result.json").read_text())["stats"]["cost_usd"] is None


def test_manifest_reports_missing_artifacts_rather_than_omitting_them(job):
    m = json.loads((job / "trajectory/Run 1/artifacts/manifest.json").read_text())
    assert m and m[0]["source"] == "/tmp/final_state.json"
    assert m[0]["status"] == "missing"
    assert m[0]["service"] == "sandbox"


# --- phase timings + cost estimate ----------------------------------------

def test_agent_execution_span_is_recorded(tmp_path, task_dir):
    jd = tmp_path / "j"
    timings = {"started_at": "2026-08-17T10:00:00.0Z",
               "finished_at": "2026-08-17T10:05:00.0Z",
               "environment_setup": None, "agent_setup": None,
               "agent_execution": {"started_at": "2026-08-17T10:00:01.0Z",
                                   "finished_at": "2026-08-17T10:04:00.0Z"},
               "verifier": {"started_at": "2026-08-17T10:04:00.0Z",
                            "finished_at": "2026-08-17T10:05:00.0Z"}}
    write_harbor_trial(jd, 1, record=RECORD, model="m", judge_result=JUDGE,
                       task_dir=task_dir, grading_dir=task_dir / "tests",
                       job_id="j", job_label="l", timings=timings)
    res = json.loads((jd / "trajectory/Run 1/result.json").read_text())
    assert res["agent_execution"]["started_at"] == "2026-08-17T10:00:01.0Z"
    assert res["verifier"]["finished_at"] == "2026-08-17T10:05:00.0Z"
    # Unmeasured phases stay null rather than being attributed to an attempt.
    assert res["environment_setup"] is None and res["agent_setup"] is None


def test_cost_estimate_is_labelled_and_never_lands_in_cost_usd(tmp_path, task_dir):
    jd = tmp_path / "j"
    rec = dict(RECORD, usage={"input_tokens": 1_000_000, "output_tokens": 100_000,
                              "cache_read_tokens": 0, "cost_usd": 0.0})
    write_harbor_trial(jd, 1, record=rec, model="claude-opus-4-8",
                       judge_result=JUDGE, task_dir=task_dir,
                       grading_dir=task_dir / "tests", job_id="j", job_label="l")
    ar = json.loads((jd / "trajectory/Run 1/result.json").read_text())["agent_result"]
    assert ar["cost_usd"] is None                      # not a measurement
    assert ar["metadata"]["is_measured"] is False
    assert "cost_usd" not in ar["metadata"]             # estimate never renamed
    assert ar["metadata"]["cost_usd_estimate"] == 22.5   # 1M*15 + 0.1M*75


def test_measured_cost_suppresses_the_estimate(tmp_path, task_dir):
    jd = tmp_path / "j"
    rec = dict(RECORD, usage={"input_tokens": 10, "output_tokens": 5, "cost_usd": 4.59})
    write_harbor_trial(jd, 1, record=rec, model="claude-opus-4-8",
                       judge_result=JUDGE, task_dir=task_dir,
                       grading_dir=task_dir / "tests", job_id="j", job_label="l")
    ar = json.loads((jd / "trajectory/Run 1/result.json").read_text())["agent_result"]
    assert ar["cost_usd"] == 4.59
    assert ar["metadata"] is None


# --- logs mirror -----------------------------------------------------------

def test_logs_mirror_is_written(job):
    logs = job / "logs"
    for n in ("INDEX.md", "job-config.json", "job-lock.json", "job-result.json",
              "pass-summary.json"):
        assert (logs / n).is_file(), n


def test_mirror_is_byte_identical_to_its_source(job):
    for src, dest in (("config.json", "job-config.json"),
                      ("lock.json", "job-lock.json"),
                      ("result.json", "job-result.json"),
                      ("pass_summary.json", "pass-summary.json")):
        assert (job / src).read_bytes() == (job / "logs" / dest).read_bytes()


def test_per_trial_subdir_named_by_trial_name(job):
    tn = json.loads((job / "trajectory/Run 1/config.json").read_text())["trial_name"]
    d = job / "logs" / tn
    assert d.is_dir()
    for n in ("report.json", "result.json", "trial-config.json",
              "verifier-ctrf.json", "verifier-reward.json",
              "verifier-reward-raw.json", "agent-stream.txt"):
        assert (d / n).is_file(), n


def test_index_lists_only_files_that_exist(job):
    """The reference INDEX.md advertises files it does not ship. An index that
    lists absent files reads as evidence they were produced."""
    import re
    text = (job / "logs" / "INDEX.md").read_text()
    for rel in re.findall(r"^- `([^`]+)`", text, re.M):
        assert (job / "logs" / rel).is_file(), rel


def test_index_reports_real_byte_sizes(job):
    import re
    text = (job / "logs" / "INDEX.md").read_text()
    for rel, size in re.findall(r"^- `([^`]+)` — (\d+) bytes", text, re.M):
        assert (job / "logs" / rel).stat().st_size == int(size)


def test_absent_optional_files_are_simply_not_indexed(job):
    """judge_response.txt is absent unless the narrative judge ran."""
    text = (job / "logs" / "INDEX.md").read_text()
    assert "judge-response.txt" not in text


def test_run_10_sorts_after_run_9(tmp_path, task_dir):
    from scripts.aggregate_logs import _run_sort_key
    dirs = [tmp_path / f"Run {i}" for i in (1, 2, 9, 10, 11)]
    assert sorted(dirs, key=_run_sort_key) == dirs


# --- schema ----------------------------------------------------------------

def _types(obj):
    """Shallow {key: type-name} map, with None recorded as 'null'."""
    return {k: ("null" if v is None else type(v).__name__) for k, v in obj.items()}


def test_trial_result_keyset(job):
    r = json.loads((job / "trajectory/Run 1/result.json").read_text())
    assert set(r) == {
        "id", "task_name", "trial_name", "trial_uri", "task_id", "source",
        "task_checksum", "config", "agent_info", "agent_result",
        "verifier_result", "exception_info", "started_at", "finished_at",
        "environment_setup", "agent_setup", "agent_execution", "verifier",
        "step_results"}
    assert set(r["agent_result"]) == {"n_input_tokens", "n_cache_tokens",
                                      "n_output_tokens", "cost_usd",
                                      "rollout_details", "metadata"}
    assert set(r["agent_info"]) == {"name", "version", "model_info"}


def test_job_result_keyset(job):
    r = json.loads((job / "result.json").read_text())
    assert set(r) == {"id", "started_at", "updated_at", "finished_at",
                      "n_total_trials", "stats"}
    ev = next(iter(r["stats"]["evals"].values()))
    assert set(ev) == {"n_trials", "n_errors", "metrics", "pass_at_k",
                       "reward_stats", "exception_stats"}


def test_locks_declare_their_schema_versions(job):
    assert json.loads((job / "lock.json").read_text())["schema_version"] == 2
    assert json.loads(
        (job / "trajectory/Run 1/lock.json").read_text())["schema_version"] == 1


def test_verifier_reward_is_a_number_not_a_string(job):
    for n in ("reward.json", "reward_raw.json"):
        v = json.loads((job / "trajectory/Run 1/verifier" / n).read_text())["reward"]
        assert isinstance(v, (int, float)) and not isinstance(v, bool)


def test_every_emitted_json_parses(job):
    for p in job.rglob("*.json"):
        json.loads(p.read_text())


def test_retry_exclusions_are_carried(job):
    lock = json.loads((job / "lock.json").read_text())
    assert len(lock["retry"]["exclude_exceptions"]) == 9
    assert "VerifierTimeoutError" in lock["retry"]["exclude_exceptions"]


def test_producer_is_named_in_the_job_lock(job):
    """complex-mcp is not Harbor; the lock says who actually produced this."""
    lock = json.loads((job / "lock.json").read_text())
    assert lock["producer"]["name"] == PRODUCER
    assert "harbor" not in lock
