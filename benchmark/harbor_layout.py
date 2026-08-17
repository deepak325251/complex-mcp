"""Harbor-native output layout (`--layout harbor`).

Emits, per task:

    output/<task-slug>/
    ├── .raw/…                  the mcp-stump layout, verbatim and untouched
    ├── trajectory/Run N/…      the Harbor-shaped trial (capital R, literal space)
    ├── config.json  lock.json  result.json  pass_summary.json
    └── logs/…                  flat mirror (scripts/aggregate_logs.py)

`.raw` sits BESIDE the Harbor tree rather than being replaced by it: the reshape
has no slot for `diagnosis.json`, `trace.jsonl`, the world snapshots or the
per-key state detail, and those are the parts a training pipeline actually reads.
Nothing is relocated, only added.

Two conventions worth stating once, because getting either wrong is silent:

**Fraction vs percentage.** `verifier/reward_raw.*` is the fraction; `reward.*`
is the same number times 100. Every conversion goes through `pct()` -- an inline
`* 100` somewhere else is how `0.447` ends up reported as `0.447%`.

**`reward` is not `final_reward`.** `reward` is the weighted ledger the harness
scored the run with (state + plan + traj + rubric). `final_reward` is the mean of
the pytest and rubric percentages, which is a *reporting* number covering two of
those channels. On a single-channel task they coincide; here they do not, and
comparing them is meaningless.

Nothing in this module fabricates provenance. complex-mcp is not Harbor and does
not drive claude-code, so `agent.name` is `complexmcp`, there is no
`agent/sessions/`, and checksums are computed rather than copied.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.parse
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from benchmark.runreport import RubricEntry, RunReport, pass_summary_rows
from benchmark.weighted_judge import traj_test_rows

SCHEMA_VERSION_JOB = 2
SCHEMA_VERSION_TRIAL = 1
PRODUCER = "complexmcp"

# Harbor's default retry exclusions, carried so downstream tooling that reads
# lock.json finds the field it expects.
RETRY_EXCLUDE = [
    "VerifierTimeoutError", "VerifierOutputParseError", "ModelNotFoundError",
    "ApiUsageLimitError", "AgentSafetyRefusalError", "AgentTimeoutError",
    "AgentAuthenticationError", "RewardFileEmptyError", "RewardFileNotFoundError",
]

# Widths measured off the reference layout:
#   job   "model-training-ckpt-codec-reco"   -> 30
#   trial "model-training-ckpt-codec-recove" -> 32
_JOB_NAME_WIDTH = 30
_TRIAL_NAME_WIDTH = 32


# ---------------------------------------------------------------------------
# scale + rounding -- one implementation, used everywhere
# ---------------------------------------------------------------------------

def _round(value, places: int):
    """Half-UP rounding.

    Python's `round` is half-to-EVEN, so the mean of 33.33 and 60.00 (= 46.665)
    lands on 46.66 rather than 46.67 -- off by a cent against every other tool
    that reports these percentages, and inconsistently so (it depends on the
    preceding digit's parity).
    """
    if value is None:
        return None
    return float(Decimal(repr(float(value))).quantize(
        Decimal("1." + "0" * places), rounding=ROUND_HALF_UP))


def pct(fraction, places: int = 4):
    """Fraction -> percentage. THE conversion; never inline a `* 100`."""
    if fraction is None:
        return None
    return _round(float(fraction) * 100.0, places)


def _mean(values):
    vals = [v for v in values if v is not None]
    return _round(sum(vals) / len(vals), 2) if vals else None


def _utc(dt: datetime | None = None) -> str:
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


# ---------------------------------------------------------------------------
# identity -- computed, never copied from the reference
# ---------------------------------------------------------------------------

def task_digest(task_dir) -> str | None:
    """`sha256:<hex>` over a task directory: every file's relative path and
    bytes, walked in sorted order so the digest is stable across machines."""
    if not task_dir or not Path(task_dir).is_dir():
        return None
    h = hashlib.sha256()
    root = Path(task_dir)
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return f"sha256:{h.hexdigest()}"


def _token(seed: str, n: int = 7) -> str:
    """Deterministic short suffix, so a re-run reproduces its trial name."""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    digest = hashlib.sha256(seed.encode()).digest()
    return "".join(alphabet[b % len(alphabet)] for b in digest[:n])


def slug_of(task_name: str) -> str:
    return task_name.split("/", 1)[1] if "/" in task_name else task_name


def job_name(task_name: str, stamp: str) -> str:
    return f"{slug_of(task_name)[:_JOB_NAME_WIDTH]}-{stamp}"


def trial_name(task_name: str, digest: str | None) -> str:
    return f"{slug_of(task_name)[:_TRIAL_NAME_WIDTH]}__{_token(digest or task_name)}"


def _honest_cost(usage: dict | None):
    """`cost_usd`, or None when the backend reported 0.0 while actually spending
    tokens. Shipping 0.0 there states a measurement that was never taken."""
    usage = usage or {}
    cost = usage.get("cost_usd")
    if not cost and (usage.get("output_tokens") or usage.get("input_tokens")):
        return None
    return cost


# USD per million tokens, per billed class. Cache writes bill at 1.25x input
# (5-minute TTL) and cache READS at 0.1x -- a 10x difference, so folding reads in
# at the input rate turns a $6 run into a $13 one. Only used for the
# clearly-labelled ESTIMATE below, never written to `cost_usd`, which is reserved
# for what the backend actually reported: an out-of-date table must not quietly
# become a fabricated measurement.
_PRICES = {
    #                     input   output  cache_write  cache_read
    "claude-opus-4-8":   (15.0,   75.0,   18.75,       1.50),
    "claude-opus-4":     (15.0,   75.0,   18.75,       1.50),
    "claude-sonnet-4-5": (3.0,    15.0,   3.75,        0.30),
    "claude-sonnet-4":   (3.0,    15.0,   3.75,        0.30),
    "claude-haiku-4-5":  (1.0,    5.0,    1.25,        0.10),
}


def _cost_estimate(model: str, usage: dict | None) -> dict | None:
    """A labelled cost estimate for when the backend reports none.

    Rides in `agent_result.metadata`, never in `cost_usd`, so a reader can always
    tell a measurement from a calculation.

    Prices each token class at its own rate and returns the per-class breakdown,
    so the number is auditable rather than a bare total. `reasoning_tokens` are
    NOT added: Anthropic already counts thinking inside `output_tokens`, and
    adding them again would double-bill the most expensive class.

    ccbridge fronts a Claude Code subscription, which has no per-request charge,
    so this is "what this run would cost at API list price" -- useful for
    comparing runs, not a bill.
    """
    usage = usage or {}
    if usage.get("cost_usd"):
        return None
    key = next((k for k in _PRICES if str(model).startswith(k)), None)
    if not key:
        return None
    p_in, p_out, p_write, p_read = _PRICES[key]
    counts = {
        "input": (usage.get("input_tokens") or 0, p_in),
        "output": (usage.get("output_tokens") or 0, p_out),
        "cache_write": (usage.get("cache_creation_tokens") or 0, p_write),
        "cache_read": (usage.get("cache_read_tokens") or 0, p_read),
    }
    if not any(n for n, _ in counts.values()):
        return None
    breakdown = {k: _round(n * rate / 1e6, 6) for k, (n, rate) in counts.items()}
    return {
        "cost_usd_estimate": _round(sum(breakdown.values()), 6),
        "cost_breakdown_usd": breakdown,
        "tokens": {k: n for k, (n, _) in counts.items()},
        "rates_usd_per_mtok": {"input": p_in, "output": p_out,
                               "cache_write": p_write, "cache_read": p_read},
        "estimate_basis": f"{key} list price; thinking tokens already counted in "
                          f"output; subscription runs have no per-request charge",
        "is_measured": False,
    }


# ---------------------------------------------------------------------------
# report.json
# ---------------------------------------------------------------------------

def build_report(model: str, run_no: int, judge_result: dict,
                 grading_dir=None, rubric_result: dict | None = None) -> dict:
    """report.json in the delivered shape.

    Two conventions collide here and the collision is silent, so it is resolved
    explicitly rather than delegated:

    `runreport.weighted_percentage` reads a negative-weight entry's `passed` as
    "the forbidden thing HELD" (its `damaged_negative` rows carry passed=True).
    `traj_test_rows` returns the OUTCOME instead -- a guard that did not fire
    reads passed=True, because that is what "this test passed" means to anyone
    reading the file. Feeding outcome-semantics rows into that function counts a
    guard doing its job as a penalty and can drive the score NEGATIVE (observed:
    -9.09% on a run whose real pytest score was 33.33%).

    So the pytest block is rendered directly, in outcome semantics, and the
    headline percentage is the ledger's own `traj_tests` value (D1) rather than
    a recomputation -- which also guarantees report.json cannot drift from the
    reward the run was actually scored with. `runreport.RubricEntry` is still
    used for the rubric rows; it has no polarity ambiguity.
    """
    rows, traj_value = traj_test_rows(judge_result, grading_dir)
    n_pass = sum(1 for r in rows if r["passed"])

    rubric: list[RubricEntry] = []
    for c in (rubric_result or {}).get("per_criterion") or []:
        rubric.append(RubricEntry(
            number=str(c.get("number", "?")),
            criterion=c.get("criterion", ""),
            type=c.get("type", ""),
            evaluation_target=c.get("evaluation_target", "final_answer"),
            importance=c.get("importance", "important"),
            score=float(c.get("score", 1) or 0),
            is_positive=bool(c.get("is_positive", True)),
            passed=bool(c.get("satisfied")),
            justification=c.get("justification", "") or "",
        ))

    test_p = pct(traj_value, 2)
    rub_p = pct(judge_result.get("rubric_score"), 2)
    if rub_p is None and rubric:
        # Rubric ran but the ledger carried no score (weight 0): recompute from
        # the criteria so the reported percentage matches the rows beside it.
        rep = RunReport(model=model, run_index=run_no, rubric=rubric)
        rub_p = pct(rep.rubric_score, 2)

    return {
        "model": model,
        "run_index": run_no,
        "include_multimodal": False,
        "pytest": {
            "passed": n_pass,
            "failed": len(rows) - n_pass,
            "exit_code": 0 if n_pass == len(rows) else 1,
            "reward": _round(traj_value, 4),
            "tests": [{"name": r["name"], "weight": r["weight"],
                       "passed": r["passed"]} for r in rows],
        },
        "rubric": [r.as_dict() for r in rubric],
        "final_reward": _mean([test_p, rub_p]),
        "test_weights_percentage": test_p,
        "rubric_weights_percentage": rub_p,
    }


def render_judge_response(rubric_result: dict | None) -> str | None:
    """`judge_response.txt` from per-criterion justifications, or None.

    Returns None when no criterion carries a justification -- i.e. the YES/NO
    judge ran and produced no prose. Emitting a file that merely restates the
    verdicts would look like a written assessment that never happened.
    """
    rows = (rubric_result or {}).get("per_criterion") or []
    parts = [f"**{r.get('number')}: {r.get('criterion', '')}**\n"
             f"{r.get('justification', '').strip()}"
             for r in rows if (r.get("justification") or "").strip()]
    if not parts:
        return None
    return ("Per-criterion assessment of the agent's final message.\n\n"
            + "\n\n".join(parts) + "\n")


# ---------------------------------------------------------------------------
# trial
# ---------------------------------------------------------------------------

def write_harbor_trial(job_dir: Path, run_no: int, *, record: dict, model: str,
                       judge_result: dict, task_dir=None, grading_dir=None,
                       rubric_result: dict | None = None,
                       atif_doc: dict | None = None,
                       job_id: str = "", job_label: str = "",
                       timings: dict | None = None,
                       judge_response: str | None = None) -> dict:
    """Write `trajectory/Run N/`. Returns a summary row for the job aggregate."""
    job_dir = Path(job_dir)
    run_dir = job_dir / "trajectory" / f"Run {run_no}"
    (run_dir / "agent").mkdir(parents=True, exist_ok=True)
    (run_dir / "verifier").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    task_name = record.get("name", "")
    digest = task_digest(task_dir)
    tname = trial_name(task_name, digest)
    reward = judge_result.get("reward")
    usage = record.get("usage") or {}
    timings = timings or {}

    # --- agent ------------------------------------------------------------
    if atif_doc is not None:
        _dump(run_dir / "agent" / "trajectory.json", atif_doc)
    # The raw agent stream. Named for its real producer -- calling it
    # claude-code.txt would assert a provenance this run does not have.
    (run_dir / "agent" / f"{PRODUCER}.txt").write_text(record.get("output", ""))

    # --- verifier ---------------------------------------------------------
    v = run_dir / "verifier"
    (v / "reward_raw.json").write_text(json.dumps({"reward": reward}))
    (v / "reward_raw.txt").write_text(str(reward))
    _dump(v / "reward.json", {"reward": pct(reward)})
    (v / "reward.txt").write_text(str(pct(reward)))

    rows, traj_value = traj_test_rows(judge_result, grading_dir)
    n_pass = sum(1 for r in rows if r["passed"])
    _dump(v / "ctrf.json", {"results": {
        # Names the real producer of these rows: pytest only when the trajectory
        # suite actually ran, else the weighted ledger.
        "tool": {"name": "pytest" if rows else "complexmcp-weighted",
                 "version": _pytest_version() if rows else ""},
        "summary": {"tests": len(rows), "passed": n_pass,
                    "failed": len(rows) - n_pass, "pending": 0, "skipped": 0,
                    "other": 0,
                    "overall_score": _round(traj_value, 4),
                    "weighted_percentage": pct(traj_value)},
        "tests": [{"name": r["name"],
                   "status": "passed" if r["passed"] else "failed",
                   "duration": 0} for r in rows],
    }})
    (v / "test-stdout.txt").write_text(_verifier_stdout(rows, traj_value, reward))

    # --- report -----------------------------------------------------------
    report = build_report(model, run_no, judge_result, grading_dir, rubric_result)
    _dump(run_dir / "report.json", report)

    # Written only when a narrative judge actually produced evidence. With the
    # YES/NO judge there is nothing to say, and an empty or synthesised file
    # would read as a judgement that was never made.
    jr = judge_response or render_judge_response(rubric_result)
    if jr:
        (run_dir / "judge_response.txt").write_text(jr)

    # --- config / lock / result -------------------------------------------
    trial_lock = _trial_lock(task_name, task_dir, digest, model)
    _dump(run_dir / "lock.json", trial_lock)
    _dump(run_dir / "config.json", {
        "task": {"path": str(task_dir) if task_dir else None},
        "trial_name": tname,
        "trials_dir": f"output/{job_label}",
        "agent_setup_timeout_multiplier": 6.0,
        "agent": {"name": PRODUCER, "model_name": model},
        "job_id": job_id,
    })
    _dump(run_dir / "result.json", _trial_result(
        tname=tname, task_name=task_name, task_dir=task_dir, digest=digest,
        model=model, reward=reward, usage=usage, job_id=job_id,
        job_label=job_label, timings=timings, lock=trial_lock,
        exception=record.get("exception_info")))

    # --- artifacts ---------------------------------------------------------
    _dump(run_dir / "artifacts" / "manifest.json",
          _artifact_manifest(task_dir, run_dir))

    return {
        "run": run_no, "trial_name": tname,
        "reward": reward,
        "passed": bool(judge_result.get("passed")),
        "test_weights_percentage": report["test_weights_percentage"],
        "rubric_weights_percentage": report["rubric_weights_percentage"],
        "final_reward": report["final_reward"],
        "usage": usage, "lock": trial_lock,
    }


def _pytest_version() -> str:
    try:
        import pytest
        return pytest.__version__
    except Exception:
        return ""


def _verifier_stdout(rows, traj_value, reward) -> str:
    lines = [f"[{'PASS' if r['passed'] else 'FAIL'}] {r['name']} "
             f"(weight {r['weight']:+g})" for r in rows]
    lines.append(f"[grade] traj_tests={traj_value}  ledger_reward={reward}")
    return "\n".join(lines) + "\n"


def _artifact_manifest(task_dir, run_dir) -> list:
    """Declared artifacts from the task's own task.toml, plus whatever this
    trial actually captured. `status` reports what happened -- an artifact the
    run never produced says `missing`, it is not quietly omitted."""
    entries = []
    declared = []
    toml_path = Path(task_dir) / "task.toml" if task_dir else None
    if toml_path and toml_path.exists():
        try:
            import tomllib
            declared = tomllib.loads(toml_path.read_text()).get("artifacts", []) or []
        except Exception:
            declared = []
    for a in declared:
        src = a.get("source") if isinstance(a, dict) else str(a)
        service = a.get("service") if isinstance(a, dict) else None
        dest = f"artifacts/{Path(src).name}"
        entries.append({
            "source": src, "destination": dest, "type": "file",
            "status": "ok" if (run_dir / dest).exists() else "missing",
            "service": service,
        })
    return entries


def _trial_lock(task_name, task_dir, digest, model) -> dict:
    return {
        "schema_version": SCHEMA_VERSION_TRIAL,
        "task": {"name": task_name, "type": "local", "digest": digest,
                 "path": str(task_dir) if task_dir else None},
        "install_only": False,
        "timeout_multiplier": 1.0,
        "agent_setup_timeout_multiplier": 6.0,
        "agent": {"name": PRODUCER, "model_name": model, "skills": [],
                  "resume_trajectory": False, "extra_allowed_hosts": [],
                  "kwargs": {}, "mcp_servers": []},
        "skills": [],
        "environment": {"type": "docker", "force_build": False, "delete": True,
                        "cpu_enforcement_policy": "auto",
                        "memory_enforcement_policy": "auto",
                        "extra_docker_compose": [], "kwargs": {},
                        "extra_allowed_hosts": []},
        "verifier": {"disable": False},
    }


def _trial_result(*, tname, task_name, task_dir, digest, model, reward, usage,
                  job_id, job_label, timings, lock, exception) -> dict:
    uri = None
    if task_dir:
        uri = "file://" + urllib.parse.quote(str(Path(task_dir).resolve()))
    return {
        "id": str(uuid.uuid4()),
        "task_name": task_name,
        "trial_name": tname,
        "trial_uri": uri,
        "task_id": {"path": str(task_dir) if task_dir else None},
        "source": None,
        # Distinct from task.digest: the digest identifies the task package,
        # this is the checksum recorded on the result. Both are recomputed.
        "task_checksum": (digest or "").removeprefix("sha256:") or None,
        "config": {
            "task": {"path": str(task_dir) if task_dir else None, "git_url": None,
                     "git_commit_id": None, "name": task_name, "ref": None,
                     "overwrite": False, "download_dir": None, "source": None},
            "trial_name": tname,
            "trials_dir": f"output/{job_label}",
            "install_only": False,
            "timeout_multiplier": 1.0,
            "agent_timeout_multiplier": None,
            "verifier_timeout_multiplier": None,
            "agent_setup_timeout_multiplier": 6.0,
            "environment_build_timeout_multiplier": None,
            "agent": dict(lock["agent"], import_path=None, n_concurrent=None,
                          concurrency_group=None, override_timeout_sec=None,
                          override_setup_timeout_sec=None, max_timeout_sec=None,
                          load_trajectory=None),
            "environment": dict(lock["environment"], import_path=None,
                                override_cpus=None, override_memory_mb=None,
                                override_storage_mb=None, override_gpus=None,
                                override_tpu=None, mounts=None),
            "verifier": {"override_timeout_sec": None, "max_timeout_sec": None,
                         "disable": False},
            "artifacts": [],
            "extra_instruction_paths": [],
            "job_id": job_id,
        },
        "agent_info": {"name": PRODUCER, "version": _producer_version(),
                       "model_info": {"name": model, "provider": None}},
        "agent_result": {
            "n_input_tokens": usage.get("input_tokens"),
            "n_cache_tokens": usage.get("cache_read_tokens"),
            "n_output_tokens": usage.get("output_tokens"),
            "cost_usd": _honest_cost(usage),
            "rollout_details": None,
            # Estimate lives here, explicitly flagged, so an unmeasured cost is
            # still informative without `cost_usd` claiming to be a measurement.
            "metadata": _cost_estimate(model, usage),
        },
        "verifier_result": {"rewards": {"reward": reward}},
        "exception_info": exception,
        "started_at": timings.get("started_at"),
        "finished_at": timings.get("finished_at"),
        "environment_setup": timings.get("environment_setup"),
        "agent_setup": timings.get("agent_setup"),
        "agent_execution": timings.get("agent_execution"),
        "verifier": timings.get("verifier"),
        "step_results": None,
    }


def _producer_version() -> str:
    try:
        import tomllib
        root = Path(__file__).resolve().parent.parent
        data = tomllib.loads((root / "pyproject.toml").read_text())
        return (data.get("project") or {}).get("version") or "0.0.0"
    except Exception:
        return "0.0.0"


# ---------------------------------------------------------------------------
# job
# ---------------------------------------------------------------------------

def write_harbor_job(job_dir: Path, *, task_name: str, task_dir, model: str,
                     trials: list[dict], job_id: str, job_label: str,
                     started_at: str, finished_at: str,
                     pass_at_k: dict | None = None) -> Path:
    """Write the job-level files once every trial has landed."""
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)

    _dump(job_dir / "config.json", {
        "job_name": job_label,
        "jobs_dir": "output",
        "agent_setup_timeout_multiplier": 6.0,
        "n_concurrent_trials": 1,
        "agents": [{"name": PRODUCER, "model_name": model}],
        "tasks": [{"path": str(task_dir) if task_dir else None}],
    })

    _dump(job_dir / "lock.json", {
        "schema_version": SCHEMA_VERSION_JOB,
        "created_at": started_at,
        # complex-mcp is not Harbor; naming the real producer here is the point.
        "producer": {"name": PRODUCER, "version": _producer_version()},
        "n_concurrent_trials": 1,
        "retry": {"max_retries": 0, "exclude_exceptions": RETRY_EXCLUDE,
                  "wait_multiplier": 1.0, "min_wait_sec": 1.0, "max_wait_sec": 60.0},
        "trials": [t["lock"] for t in trials],
    })

    rewards: dict = {}
    for t in trials:
        rewards.setdefault(str(t["reward"]), []).append(t["trial_name"])
    tot = lambda k: sum((t["usage"] or {}).get(k) or 0 for t in trials)  # noqa: E731
    costs = [_honest_cost(t["usage"]) for t in trials]

    _dump(job_dir / "result.json", {
        "id": job_id,
        "started_at": started_at,
        "updated_at": finished_at,
        "finished_at": finished_at,
        "n_total_trials": len(trials),
        "stats": {
            "n_completed_trials": len(trials),
            "n_errored_trials": 0, "n_running_trials": 0,
            "n_pending_trials": 0, "n_cancelled_trials": 0, "n_retries": 0,
            "evals": {f"{PRODUCER}__{model}__adhoc": {
                "n_trials": len(trials),
                "n_errors": 0,
                "metrics": [{"mean": _mean_raw([t["reward"] for t in trials])}],
                "pass_at_k": pass_at_k or {},
                "reward_stats": {"reward": rewards},
                "exception_stats": {},
            }},
            "n_input_tokens": tot("input_tokens"),
            "n_cache_tokens": tot("cache_read_tokens"),
            "n_output_tokens": tot("output_tokens"),
            # None when any trial could not report a real cost, rather than a
            # total that silently treats unknown as zero.
            "cost_usd": None if any(c is None for c in costs) else sum(costs),
        },
    })

    # Shape lives in runreport (its documented home); the half-up mean is passed
    # in so every percentage in the tree rounds the same way.
    _dump(job_dir / "pass_summary.json", pass_summary_rows(
        model,
        [{"run_index": t["run"],
          "test_weights_percentage": t["test_weights_percentage"],
          "rubric_weights_percentage": t["rubric_weights_percentage"],
          "combined_score": t["final_reward"]} for t in trials],
        mean=_mean))

    # Flat mirror, generated last so it indexes everything above. Failure here
    # must not lose the job files that were already written correctly.
    try:
        from scripts.aggregate_logs import aggregate as _aggregate_logs
        _aggregate_logs(job_dir)
    except Exception as exc:
        print(f"[logs] mirror skipped: {type(exc).__name__}: {exc}")
    return job_dir


def _mean_raw(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


# ---------------------------------------------------------------------------

def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=4, default=str))
