"""mcp-stump CLI.

Wraps `harbor run` so a single command performs the whole stump protocol:

    oracle control  ->  nop control  ->  n attempts  ->  score  ->  classify
    ->  pass@k / pass^k  ->  paired export

Output layout -- one directory per task, one subdirectory per run:

    out/trials_<task>/
      summary.json          pass@k, pass^k, CI, validity, usage, failure breakdown
      pairs.jsonl           failed x gold trajectory pairs (the training artifact)
      failure_analysis.json labelled modes with evidence
      ground_truth/         initial_state, expected_state, judge_spec, gold_plan
      controls/
        oracle/  nop/       reward.json, ctrf.json, trace.jsonl
      run1/ run2/ ...       one per attempt:
        trajectory.json       ATIF
        trace.jsonl           environment trace
        reward.json           the 9 metrics
        detail.json           full judge + graph breakdown
        ctrf.json             per-key-path results
        diagnosis.json        labelled failure mode
        agent.log             raw agent stdout

Harbor's own job directories (lock.json, config.json, session state, per-trial
logs) are harvested for the files above and then discarded -- keep them with
--keep-raw when debugging the harness itself.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import atif
from .classify import classify
from .verify.efs import EFSIndex
from .facade.trace import load_trace, summarize
from .package import package as build_bundle
from .report import AttemptResult, TaskSummary, Usage, write_job_summary
from .runreport import RubricEntry
from .derive import compare_authored, derive as do_derive
from .rescore import rescore as do_rescore
from .taskkit.catalog import affordances, load as load_catalog
from .taskkit.scaffold import create as scaffold_task
from .world import load_contract, preflight as do_preflight
from .runreport import RunReport, from_judge, load_rubric, write_pass_summary

app = typer.Typer(add_completion=False, help="Hybrid MCP stumping harness (Harbor format).")
console = Console()

DEFAULT_KS = "1,2,8"

# Bounded retries for infrastructure failures before one is accepted as a
# result. Model failures are never retried.
INFRA_RETRIES = 2


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------

@app.command()
def run(
    task: Path = typer.Argument(..., help="Path to a Harbor task directory."),
    out: Path = typer.Option(Path("out"), "--out", "-o", help="Output root."),
    job: str = typer.Option("stump", "--job", "-j", help="Job name."),
    attempts: int = typer.Option(8, "--attempts", "-n", help="Rollouts against the target."),
    ks: str = typer.Option(DEFAULT_KS, "--at", help="Comma-separated k for pass@k / pass^k, e.g. 1,2,8"),
    agent: str = typer.Option("claude-code", "--agent", "-a", help="Harbor agent."),
    model: str = typer.Option("anthropic/claude-opus-4-8", "--model", "-m"),
    bridge: str = typer.Option(
        os.environ.get("CCBRIDGE_URL", "http://127.0.0.1:8765"),
        "--bridge",
        help="ccbridge base URL. Trajectories run through Claude Code OAuth, not a raw API key.",
    ),
    skip_controls: bool = typer.Option(False, "--skip-controls", help="Skip oracle/nop (NOT for delivery)."),
    allow_any_tier: bool = typer.Option(False, "--any-tier", help="Run an L1/L2 task anyway."),
    concurrency: int = typer.Option(1, "--concurrency", "-c"),
    keep_going: bool = typer.Option(False, "--keep-going", help="Continue past a failed attempt."),
    keep_raw: bool = typer.Option(False, "--keep-raw", help="Keep Harbor's raw job dirs (debugging)."),
    resume: bool = typer.Option(False, "--resume", help="Do not wipe an existing trials dir."),
    analyze: bool = typer.Option(False, "--analyze", help="Run the trial-analysis rubric over the runs."),
    bundle: Optional[str] = typer.Option(None, "--bundle", help="Also emit a delivery bundle under this directory."),
) -> None:
    """Run the full stump protocol against one task."""
    k_list = _parse_ks(ks)
    task = task.resolve()
    job_dir = (out / f"trials_{task.name}").resolve()
    if job_dir.exists() and not resume:
        shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    raw_root = job_dir / ".raw"

    if _stage_package(task):
        console.print("[dim]  staged scoring package into tests/ (was stale)[/dim]")
    meta = _read_task_meta(task)
    console.rule(f"[bold]{meta['name']}")
    console.print(f"  levers   : {', '.join(meta['levers']) or '(none declared)'}")
    console.print(f"  seed     : {meta['seed']}")
    console.print(f"  knobs    : {meta['knobs']}")
    console.print(f"  agent    : {agent}  model: {model}")
    console.print(f"  bridge   : {bridge}")
    console.print(f"  tier     : {meta['tier'] or '(undeclared)'}   outcome: {meta['outcome']}")
    console.print(f"  attempts : {attempts}   reporting at k={k_list}")

    if meta["tier"] and meta["tier"] not in TESTABLE_TIERS and not allow_any_tier:
        console.print(
            f"\n[red]{meta['tier']} is out of scope for harness testing "
            f"(testable: {', '.join(TESTABLE_TIERS)}).[/red]\n"
            "L1/L2 do not discriminate between frontier models, so a run spends "
            "inference to learn nothing. Pass --any-tier to override.")
        raise typer.Exit(code=2)

    env = _bridge_env(bridge)
    # The verifier runs in its own container and cannot read task.toml.
    env["MCP_STUMP_OUTCOME"] = meta["outcome"]

    oracle_reward = nop_reward = None
    if not skip_controls:
        console.print("\n[bold]controls[/bold]")
        oracle_reward = _control(task, raw_root / "oracle", "oracle", env)
        _harvest(raw_root / "oracle", job_dir / "controls" / "oracle")
        nop_reward = _control(task, raw_root / "nop", "nop", env)
        _harvest(raw_root / "nop", job_dir / "controls" / "nop")
        _report_controls(oracle_reward, nop_reward)
        if oracle_reward != 1.0 or nop_reward != 0.0:
            console.print("[red]Controls failed. The task is not admissible; "
                          "measuring it would produce a false stump.[/red]")
            if not keep_going:
                raise typer.Exit(code=2)

    console.print(f"\n[bold]{attempts} attempts[/bold]")
    results: list[AttemptResult] = []
    gold = _load_gold(raw_root / "oracle")
    _stage_ground_truth(task, job_dir / "ground_truth")

    # Model is a directory level. Flattening runs under the task means a second
    # model silently overwrites the first.
    model_dir = job_dir / "trajectories" / _slug(model)
    rubric_spec = load_rubric(task)
    run_reports: list[RunReport] = []

    for i in range(1, attempts + 1):
        # An infrastructure failure (CLI download flake, container start
        # timeout) is not evidence about the model. Letting it consume an
        # attempt biases pass@k downward and manufactures fake stumps, so
        # retry a bounded number of times before accepting it.
        for retry in range(INFRA_RETRIES + 1):
            raw = raw_root / (f"run{i}" if retry == 0 else f"run{i}-retry{retry}")
            started = time.time()
            rc = _harbor_run(task, raw, agent, env, model=model)
            run_dir = _harvest(raw, model_dir / f"run_{i}")
            result = _score_attempt(
                i, raw, meta, gold, duration=time.time() - started, infra=rc != 0,
                out_dir=run_dir,
            )
            if result.primary_mode != "infra_error" or retry == INFRA_RETRIES:
                break
            console.print(f"   {i:>2}. [yellow]infra failure, retrying "
                          f"({retry + 1}/{INFRA_RETRIES})[/yellow]")
        results.append(result)
        _print_attempt(result)

        rep = _run_report(model, i, run_dir, rubric_spec, rc)
        rep.write(run_dir / "report.json")
        run_reports.append(rep)

        # Refusal tasks are gated on BOTH halves: the verifier proved the world
        # was left alone, and the rubric -- judged here, where the trajectory
        # is -- says the decline was genuine and well-reasoned. Keyed on the
        # critical criteria rather than a numeric threshold, so a correct
        # refusal does not fail for being a sentence too long.
        if meta["outcome"] == "refusal":
            crit = [r for r in rep.rubric if r.importance.lower() == "critical"]
            crit_ok = bool(crit) and all(r.passed == r.is_positive for r in crit)
            result.passed = result.passed and crit_ok
            result.reward = 1.0 if result.passed else 0.0
            if result.passed:
                result.primary_mode = "solved"
                result.crux_aligned = None
            _rewrite_reward(run_dir, result)

    summary = TaskSummary(
        task_name=meta["name"],
        model=model,
        agent=agent,
        seed=meta["seed"],
        levers=meta["levers"],
        attempts=results,
        ks=k_list,
        oracle_reward=oracle_reward,
        nop_reward=nop_reward,
    )
    summary.write(job_dir / "summary.json")
    if run_reports:
        write_pass_summary(model, run_reports, model_dir / "pass_summary.json")
    _export_pairs(job_dir, meta, results, gold)

    # harbor analyze needs the raw Harbor job dirs, so it has to run before the
    # harvest cleans them up.
    if analyze:
        _run_analysis(raw_root, job_dir, model, env)

    if not keep_raw:
        shutil.rmtree(raw_root, ignore_errors=True)

    if bundle:
        out_dir = build_bundle(job_dir, task, Path(bundle) / task.name, model=model)
        console.print(f"  bundle   -> [cyan]{out_dir}[/cyan]")
    _print_summary(summary, k_list)
    console.print(f"\nwrote [cyan]{job_dir}[/cyan]")


# --------------------------------------------------------------------------
# suite
# --------------------------------------------------------------------------

@app.command()
def suite(
    tasks: Path = typer.Argument(..., help="Directory containing task directories."),
    out: Path = typer.Option(Path("out"), "--out", "-o"),
    job: str = typer.Option("stump", "--job", "-j"),
    attempts: int = typer.Option(8, "--attempts", "-n"),
    ks: str = typer.Option(DEFAULT_KS, "--at"),
    agent: str = typer.Option("claude-code", "--agent", "-a"),
    model: str = typer.Option("anthropic/claude-opus-4-8", "--model", "-m"),
    bridge: str = typer.Option(os.environ.get("CCBRIDGE_URL", "http://127.0.0.1:8765"), "--bridge"),
) -> None:
    """Run every task in a directory and write a corpus-level roll-up."""
    k_list = _parse_ks(ks)
    dirs = sorted(p for p in tasks.iterdir() if (p / "task.toml").exists())
    if not dirs:
        console.print(f"[red]no Harbor tasks under {tasks}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[bold]{len(dirs)} tasks[/bold] -> {out / job}")
    for t in dirs:
        run.callback(  # type: ignore[attr-defined]
            task=t, out=out, job=job, attempts=attempts, ks=ks,
            agent=agent, model=model, bridge=bridge,
            skip_controls=False, concurrency=1, keep_going=True,
        )

    summaries = []
    for t in dirs:
        s = out / job / "tasks" / t.name / "summary.json"
        if s.exists():
            summaries.append(_summary_from_json(json.loads(s.read_text()), k_list))
    path = write_job_summary(summaries, out / job / "job.json", k_list)
    console.print(f"\nwrote [cyan]{path}[/cyan]")


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------

@app.command()
def validate(
    task: Path = typer.Argument(...),
    bridge: str = typer.Option(os.environ.get("CCBRIDGE_URL", "http://127.0.0.1:8765"), "--bridge"),
) -> None:
    """Controls only: oracle must score 1.0, nop must score 0.0."""
    env = _bridge_env(bridge)
    tmp = Path(".mcp-stump-validate") / task.name
    o = _control(task, tmp / "oracle", "oracle", env)
    n = _control(task, tmp / "nop", "nop", env)
    _report_controls(o, n)
    shutil.rmtree(tmp.parent, ignore_errors=True)
    raise typer.Exit(code=0 if (o == 1.0 and n == 0.0) else 1)


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------

def _parse_ks(raw: str) -> list[int]:
    try:
        ks = sorted({int(x) for x in raw.replace("@", "").split(",") if x.strip()})
    except ValueError as exc:
        raise typer.BadParameter(f"--at expects integers like 1,2,8 (got {raw!r})") from exc
    if not ks or any(k < 1 for k in ks):
        raise typer.BadParameter("--at values must be >= 1")
    return ks


def _bridge_env(bridge: str) -> dict[str, str]:
    """Point the agent at ccbridge instead of the public API.

    ccbridge speaks the Anthropic wire format backed by Claude Code OAuth
    credentials, so no ANTHROPIC_API_KEY is consumed -- the stub value is only
    there because SDK clients refuse to start without one.
    """
    env = dict(os.environ)
    env["ANTHROPIC_API_BASE"] = bridge
    env["ANTHROPIC_BASE_URL"] = bridge
    env.setdefault("ANTHROPIC_API_KEY", "mcp-stump-ccbridge-stub")
    return env


def _harbor_run(task: Path, out: Path, agent: str, env: dict, model: str | None = None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        "harbor", "run",
        "-p", str(task),
        "--agent", agent,
        "--env", "docker",          # compose sidecars are docker-only
        "-o", str(out.parent),
        "--job-name", out.name,
    ]
    if model and agent not in ("oracle", "nop"):
        cmd += ["-m", model]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    (out / "harbor.stdout.txt").write_text(proc.stdout)
    (out / "harbor.stderr.txt").write_text(proc.stderr)
    return proc.returncode


def _control(task: Path, out: Path, agent: str, env: dict) -> float | None:
    _harbor_run(task, out, agent, env)
    return _reward(out)


# Files worth keeping from a Harbor job dir. Everything else -- lock.json,
# config.json, per-trial logs, the agent's own session state -- is harness
# bookkeeping that bloats a delivery bundle without informing anything.
_HARVEST = {
    "agent/trajectory.json": "trajectory.json",
    "artifacts/tmp/trace.jsonl": "trace.jsonl",
    "artifacts/tmp/initial_state.json": "initial_state.json",
    "artifacts/tmp/final_state.json": "final_state.json",
    "verifier/reward.json": "reward.json",
    "verifier/detail.json": "detail.json",
    "verifier/ctrf.json": "ctrf.json",
    "analysis.json": "analysis.json",
}


def _harvest(raw: Path, dest: Path) -> Path:
    """Copy the signal out of a Harbor job dir and leave the rest behind."""
    dest.mkdir(parents=True, exist_ok=True)
    trial = _find_trial(raw)
    if trial is None:
        # Nothing ran. Preserve whatever explains why.
        for name in ("exception.txt", "harbor.stderr.txt"):
            for src in raw.rglob(name):
                shutil.copy2(src, dest / name)
                break
        return dest

    for rel, out_name in _HARVEST.items():
        src = trial / rel
        if src.is_file():
            shutil.copy2(src, dest / out_name)

    # Agent stdout under whatever the agent calls itself.
    agent_dir = trial / "agent"
    if agent_dir.is_dir():
        for log in agent_dir.glob("*.txt"):
            shutil.copy2(log, dest / "agent.log")
            break

    for name in ("exception.txt",):
        src = trial / name
        if src.is_file():
            shutil.copy2(src, dest / name)

    return dest


def _stage_ground_truth(task: Path, dest: Path) -> None:
    """Copy the derived ground truth next to the runs it scored."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("initial_state.json", "expected_state.json",
                 "judge_spec.json", "gold_plan.json"):
        src = task / "tests" / name
        if src.is_file():
            shutil.copy2(src, dest / name)


def _reward(job_dir: Path) -> float | None:
    for rj in job_dir.rglob("verifier/reward.json"):
        try:
            data = json.loads(rj.read_text())
            return float(data.get("reward", data.get("accuracy", 0.0)))
        except Exception:  # noqa: BLE001
            pass
    for rt in job_dir.rglob("verifier/reward.txt"):
        try:
            return float(rt.read_text().strip())
        except Exception:  # noqa: BLE001
            pass
    return None


def _stage_package(task: Path) -> bool:
    """Copy the scoring package into the task's tests/ dir if it has drifted.

    Separate-mode verifiers skip Harbor's tests/ upload, so everything the
    verifier needs must be inside the image at build time -- which means a
    physical copy of mcp_stump under tests/. Doing that by hand (via
    scripts/materialize-task.sh) is a step that gets forgotten: at one point
    all seven tasks were carrying scoring code three fixes behind src/, so a
    run would have been graded by stale logic with nothing reporting it.

    Returns True if anything was refreshed.
    """
    src = Path(__file__).resolve().parent
    dest = task / "tests" / "mcp_stump"
    if not (task / "tests").is_dir():
        return False

    def snapshot(root: Path) -> dict[str, bytes]:
        return {
            str(f.relative_to(root)): f.read_bytes()
            for f in root.rglob("*.py") if "__pycache__" not in f.parts
        }

    if dest.is_dir() and snapshot(src) == snapshot(dest):
        return False

    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # Equal function sets are corpus-wide, not per task.
    efs = Path("registry/efs.json")
    if efs.is_file():
        shutil.copy2(efs, task / "tests" / "efs.json")
    _stage_verifier_inputs(task)
    return True


def _stage_verifier_inputs(task: Path) -> None:
    """Put everything the verifier needs INSIDE tests/.

    The verifier image is built with `tests/` as its context, so anything
    outside it simply does not exist in that container. Two things were:

      rubric.json   authored at the task root -> the judge loaded nothing, and
                    `rubric_score` came back as the absent-sentinel on a task
                    whose whole grading surface is the rubric.
      outcome       set as an env var on the agent run, which the SEPARATE
                    verifier container never sees -- so a refusal task was
                    silently graded with completion semantics and passed
                    without the rubric ever being consulted.

    Both are staged as files rather than env, because env propagation into the
    verifier is Harbor's business and not something to depend on.
    """
    import tomllib

    tests = task / "tests"
    rub = task / "rubric.json"
    if rub.is_file():
        shutil.copy2(rub, tests / "rubric.json")
    cfg = task / "task.toml"
    if cfg.is_file():
        md = tomllib.loads(cfg.read_text()).get("metadata", {})
        (tests / "outcome.txt").write_text(
            str(md.get("outcome", "completion")).strip().lower())


def _read_task_meta(task: Path) -> dict:
    import tomllib

    cfg = tomllib.loads((task / "task.toml").read_text())
    md = cfg.get("metadata", {})
    envcfg = cfg.get("environment", {})
    return {
        "name": cfg.get("task", {}).get("name", task.name),
        "levers": md.get("stump_levers", md.get("stump_modes", [])) or [],
        "seed": int(md.get("seed", envcfg.get("env", {}).get("MCP_STUMP_SEED", 0))),
        "knobs": md.get("knobs", {}),
        "tier": str(md.get("capability_level", "")).upper(),
        # "completion" (reach the goal state) or "refusal" (decline, and leave
        # the world alone). A refusal task inverts the terminal gate, so the
        # verifier has to be told which one it is scoring.
        "outcome": str(md.get("outcome", "completion")).strip().lower(),
        "instruction": (task / "instruction.md").read_text() if (task / "instruction.md").exists() else "",
    }


def _find_trial(job_dir: Path) -> Optional[Path]:
    for p in sorted(job_dir.rglob("verifier")):
        return p.parent
    return None


def _score_attempt(
    i: int, adir: Path, meta: dict, gold: dict | None, *, duration: float, infra: bool,
    out_dir: Path | None = None,
) -> AttemptResult:
    trial = _find_trial(adir)
    reward = _reward(adir) or 0.0
    usage = _usage(adir, trial)

    judge_result: dict = {}
    graph_f1 = 0.0
    trace: list[dict] = []
    traj_path = None

    if trial:
        rj = trial / "verifier" / "reward.json"
        if rj.exists():
            data = json.loads(rj.read_text())
            graph_f1 = float(data.get("graph_f1", 0.0) or 0.0)
            # reward.json is flat numerics (Harbor validates it as
            # dict[str, float|int]); the judge breakdown lives alongside it.
            # Two verifier paths emit different names for the same idea: the
            # derived spec counts key-paths (keys_reached/keys_required), the
            # authored path counts checks (checks_passed/checks_total). Reading
            # only the first left recall/total as None, and classify compared
            # None < None -- a TypeError that killed the run on attempt 1,
            # AFTER the controls had been paid for.
            judge_result = {
                "passed": float(data.get("reward", 0.0)) >= 1.0,
                "completion_rate": data.get("completion_rate") or 0.0,
                "misbehaving_rate": data.get("misbehaving_rate") or 0.0,
                "recall": data.get("keys_reached",
                                   data.get("checks_passed")) or 0,
                "total": data.get("keys_required",
                                  data.get("checks_total")) or 0,
            }
        dj = trial / "verifier" / "detail.json"
        if dj.exists():
            detail = json.loads(dj.read_text())
            judge_result = {**judge_result,
                            **(detail.get("judge") or detail.get("checks") or {})}
        # Collected artifacts rematerialise at their ORIGINAL absolute path, so
        # a sidecar's /tmp/trace.jsonl lands under artifacts/tmp/.
        for cand in (trial / "artifacts" / "tmp" / "trace.jsonl",
                     trial / "artifacts" / "trace.jsonl", trial / "trace.jsonl"):
            if cand.exists():
                trace = load_trace(cand)
                break
        tj = trial / "agent" / "trajectory.json"
        if tj.exists():
            traj_path = str(tj)

    # A trial that never got as far as running the agent is an infrastructure
    # failure, not a model failure. Harbor exits 0 for the *job* even when the
    # trial raised, so the exit code alone misses it -- and mislabelling a
    # failed CLI install as "no_tool_use" would put a fake stump in the corpus.
    infra_detail = None
    if infra:
        infra_detail = "harbor run returned non-zero"
    else:
        for exc in adir.rglob("exception.txt"):
            first = exc.read_text().strip().splitlines()
            tail = [ln for ln in first if ln and not ln.startswith((" ", "\t"))]
            infra_detail = tail[-1][:300] if tail else "trial raised an exception"
            break

    # The closing message distinguishes "stopped early" from "claimed success
    # for work it never committed" -- the same missing call, very different
    # failure.
    final_message = ""
    if traj_path:
        try:
            final_message = atif.Trajectory.load(traj_path).final_message()
        except Exception:  # noqa: BLE001
            pass

    diagnosis = classify(
        trace=trace,
        judge_result=judge_result or {"passed": reward >= 1.0},
        gold_trace=(gold or {}).get("trace"),
        levers=meta["levers"],
        infra_error=infra_detail,
        final_message=final_message,
        efs=EFSIndex.load(Path("registry/efs.json")),
    )

    target = out_dir or adir
    target.mkdir(parents=True, exist_ok=True)
    (target / "diagnosis.json").write_text(json.dumps(diagnosis.as_dict(), indent=2))
    if traj_path:
        traj_path = str(target / "trajectory.json")

    return AttemptResult(
        attempt=i,
        passed=reward >= 1.0,
        completion_rate=float(judge_result.get("completion_rate", reward)),
        misbehaving_rate=float(judge_result.get("misbehaving_rate", 0.0)),
        graph_f1=graph_f1,
        reward=reward,
        # Falls back to the binary reward when the judge did not report a
        # graded score (infra failures, missing final_state) -- never to 0.0,
        # which would read as "scored and failed" rather than "not scored".
        weighted_score=float(judge_result.get("weighted_score", reward)),
        primary_mode=diagnosis.primary_mode,
        crux_aligned=diagnosis.crux_aligned,
        call_stats=summarize(trace),
        usage=usage,
        duration_sec=duration,
        trajectory_path=traj_path,
    )


def _usage(job_dir: Path, trial: Optional[Path]) -> Usage:
    """Token/cost accounting.

    Harbor writes it to result.json.agent_result for real agents; oracle and
    nop legitimately have none. ATIF final_metrics is the fallback.
    """
    agent_result = None
    for rj in job_dir.rglob("result.json"):
        try:
            data = json.loads(rj.read_text())
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict) and data.get("agent_result"):
            agent_result = data["agent_result"]
            break

    atif_metrics = None
    if trial:
        tj = trial / "agent" / "trajectory.json"
        if tj.exists():
            try:
                atif_metrics = json.loads(tj.read_text()).get("final_metrics")
            except Exception:  # noqa: BLE001
                pass

    return Usage.from_harbor(agent_result, atif_metrics)


def _load_gold(oracle_dir: Path) -> dict | None:
    trial = _find_trial(oracle_dir)
    if not trial:
        return None
    trace = []
    for cand in (trial / "artifacts" / "tmp" / "trace.jsonl",
                 trial / "artifacts" / "trace.jsonl", trial / "trace.jsonl"):
        if cand.exists():
            trace = load_trace(cand)
            break
    tj = trial / "agent" / "trajectory.json"
    traj = atif.Trajectory.load(tj) if tj.exists() else atif.Trajectory(
        atif.synth_from_trace(trace, agent="oracle", model="oracle")
    )
    return {"trace": trace, "trajectory": traj}


def _export_pairs(job_dir: Path, meta: dict, results: list[AttemptResult], gold: dict | None) -> None:
    pairs = []
    analyses = []
    for r in results:
        if r.passed or not r.trajectory_path:
            continue
        run_dir = Path(r.trajectory_path).parent
        diag_file = run_dir / "diagnosis.json"
        diag = json.loads(diag_file.read_text()) if diag_file.exists() else {}
        trace = load_trace(run_dir / "trace.jsonl") if (run_dir / "trace.jsonl").exists() else []
        failed = atif.Trajectory.load(r.trajectory_path)
        pairs.append(
            atif.build_pair(
                task_name=meta["name"],
                seed=meta["seed"],
                instruction=meta["instruction"],
                failed=failed,
                gold=(gold or {}).get("trajectory"),
                diagnosis=diag,
                judge={"completion_rate": r.completion_rate,
                       "misbehaving_rate": r.misbehaving_rate,
                       "passed": r.passed},
                env_trace=trace,
                levers=meta["levers"],
            )
        )
        analyses.append({"attempt": r.attempt, **diag})

    if pairs:
        atif.write_pairs(pairs, job_dir / "pairs.jsonl")
    (job_dir / "failure_analysis.json").write_text(json.dumps(analyses, indent=2))


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "-" for c in str(name))


def _rewrite_reward(run_dir: Path, result) -> None:
    """Reflect the harness-side verdict back into the on-disk artifacts.

    reward.json is what every downstream consumer reads, so a verdict that
    lives only in memory would leave the bundle disagreeing with the summary.
    """
    rj = run_dir / "reward.json"
    if not rj.is_file():
        return
    data = json.loads(rj.read_text())
    data["reward"] = result.reward
    rj.write_text(json.dumps(data, indent=2))
    (run_dir / "reward.txt").write_text(str(result.reward))
    dg = run_dir / "diagnosis.json"
    if dg.is_file() and result.passed:
        d = json.loads(dg.read_text())
        d["primary_failure"] = {"mode": "solved", "category": "programmatic",
                                "explanation": "Declined correctly and left the world untouched."}
        d["crux_aligned"] = None
        dg.write_text(json.dumps(d, indent=2))


def _run_report(model: str, i: int, run_dir: Path, rubric_spec: list[dict],
                exit_code: int) -> RunReport:
    """Weighted per-key report in the reference schema.

    The rubric half stays empty unless the task ships a rubric.json -- an absent
    rubric is null, not zero, so a task without one is not scored as if it
    failed every criterion.
    """
    detail_all = {}
    dj = run_dir / "detail.json"
    if dj.is_file():
        detail_all = json.loads(dj.read_text())
    detail = detail_all.get("judge") or detail_all.get("checks") or {}
    rep = from_judge(model, i, detail, exit_code=exit_code)

    if not rubric_spec:
        return rep

    # The rubric is judged HERE, in the harness, not in the verifier.
    #
    # A separate-mode verifier runs in its own environment and Harbor uploads
    # agent logs only back to the AGENT environment -- that isolation is
    # deliberate anti-cheat design. So the verifier can never see the agent's
    # closing message, which is the only thing most rubric criteria are about.
    # Grading it there produced 0.0 on a textbook refusal.
    #
    # The split is clean and matches the two-score separation: the verifier
    # owns the deterministic half (it has the collected state), the harness
    # owns the judged half (it has the trajectory).
    from .verify import rubric as rubric_mod

    final_message = ""
    tj = run_dir / "trajectory.json"
    if tj.is_file():
        try:
            final_message = atif.Trajectory.load(tj).final_message()
        except Exception:  # noqa: BLE001
            pass
    trace = load_trace(run_dir / "trace.jsonl") if (run_dir / "trace.jsonl").is_file() else []

    rows = rubric_mod.grade(rubric_spec, final_message=final_message, trace=trace)
    rep.rubric = [RubricEntry.from_criterion(r, bool(r.get("passed")),
                                             str(r.get("justification", "")))
                  for r in rows]
    (run_dir / "rubric.json").write_text(json.dumps(rows, indent=2))

    held = sum(1 for r in rows if r.get("passed"))
    crit = [r for r in rows if str(r.get("importance", "")).lower() == "critical"]
    crit_ok = all(bool(r.get("passed")) == bool(r.get("is_positive", True)) for r in crit)
    console.print(f"        [dim]rubric: {held}/{len(rows)} criteria held, "
                  f"critical {'OK' if crit_ok else 'FAILED'}, "
                  f"score {rubric_mod.score(rows):.3f}[/dim]")
    return rep


def _run_analysis(raw_root: Path, job_dir: Path, model: str, env: dict) -> None:
    """Trial-analysis rubric: difficulty_crux and near_miss are the false-stump
    detectors, so this is a quality gate, not decoration."""
    rubric = Path("rubrics/trial-analysis.toml")
    prompt = Path("rubrics/trial-analysis-job.txt")
    if not rubric.is_file():
        console.print("  [yellow]rubrics/trial-analysis.toml not found; skipping[/yellow]")
        return
    for run in sorted(raw_root.glob("run*")):
        cmd = ["harbor", "analyze", str(run), "-m", model, "-r", str(rubric),
               "-o", str(raw_root / "analysis"), "--job-name", run.name, "-q"]
        if prompt.is_file():
            cmd += ["--prompt", str(prompt)]
        subprocess.run(cmd, env=env, capture_output=True, text=True)
    found = list((raw_root / "analysis").rglob("analysis.json"))
    if found:
        merged = [json.loads(f.read_text()) for f in found]
        (job_dir / "trial_analysis.json").write_text(json.dumps(merged, indent=2))
        console.print(f"  analysis -> {len(found)} run(s) reviewed")


# Harness testing is scoped to L3+. L1/L2 do not discriminate between frontier
# models, so a run against them spends inference to learn nothing; the scope is
# enforced rather than documented so it cannot be forgotten.
TESTABLE_TIERS = ("L3", "L4", "L5")


@app.command()
def catalog(
    query: Optional[str] = typer.Argument(None, help="Filter by app or tool name/description."),
    gates: bool = typer.Option(False, "--gates", help="Only apps with a gate (hidden_prerequisite material)."),
    tools: bool = typer.Option(False, "--tools", help="List matching tools with signatures."),
) -> None:
    """What can I build a task out of? Apps, tools, gates and state keys.

    Static -- needs no running sandbox. It says a capability EXISTS; it cannot
    say today's seed contains the data. That is `preflight`, and the two are
    complementary.
    """
    index = load_catalog()
    apps = list(index.values())
    if gates:
        apps = [a for a in apps if a.gates or a.gated_tools]
    if query:
        q = query.lower()
        apps = [a for a in apps if q in a.name.lower() or a.find(q)]

    if tools and query:
        for a in apps:
            hits = a.find(query.lower()) or a.tools
            console.print(f"\n[bold]{a.name}[/bold]")
            for t in hits[:40]:
                mark = "[red]w[/red]" if t.writes else " "
                console.print(f"  {mark} {t.signature():<44} {t.description[:70]}")
        return

    console.print(f"[bold]{len(apps)} app(s)[/bold]  "
                  f"({sum(len(a.tools) for a in apps)} tools)\n")
    console.print(f"  {'app':<22}{'tools':>6}{'writes':>7}{'gated':>6}  state keys / levers")
    for a in sorted(apps, key=lambda x: -len(x.tools)):
        flag = "" if a.gradeable else " [red](no state -- ungradeable)[/red]"
        console.print(f"  {a.name:<22}{len(a.tools):>6}{len(a.writers):>7}"
                      f"{len(a.gated_tools) + len(a.gates):>6}  "
                      f"{', '.join(a.state_keys[:4])}{flag}")
        if a.gates:
            console.print(f"  {'':<22}{'':>19}  [dim]openers: {', '.join(a.gates)}[/dim]")
        lv = affordances(a)
        if lv:
            console.print(f"  {'':<22}{'':>19}  [dim]levers: {', '.join(lv)}[/dim]")
    console.print("\n[dim]--tools with a query lists signatures; 'w' marks a write.[/dim]")


@app.command("new")
def new_task(
    name: str = typer.Argument(..., help="Task directory name, e.g. github-triage-escalation."),
    tier: str = typer.Option("L4", "--tier", help="L3, L4 or L5."),
    apps: str = typer.Option(..., "--apps", help="Comma-separated app names (see `catalog`)."),
    levers: str = typer.Option("hidden_prerequisite,dirty_state,long_chain,cross_server",
                               "--levers", help="Comma-separated stump levers."),
    outcome: str = typer.Option("completion", "--outcome", help="completion | refusal."),
    seed: int = typer.Option(777, "--seed"),
    distractors: int = typer.Option(800, "--distractors"),
) -> None:
    """Scaffold a task: every file, pre-filled with facts read from the catalogue.

    State paths, gate openers and verifier wiring come from the app sources, so
    they are real. Instruction prose, assertions and oracle logic are left TODO
    -- a plausible-looking wrong default is worse than an obvious gap.
    """
    app_list = [a.strip() for a in apps.split(",") if a.strip()]
    lever_list = [l.strip() for l in levers.split(",") if l.strip()]
    if tier.upper() not in TESTABLE_TIERS:
        console.print(f"[red]{tier} is out of scope; testable tiers are "
                      f"{', '.join(TESTABLE_TIERS)}.[/red]")
        raise typer.Exit(code=2)
    if outcome == "refusal" and "refusal" not in lever_list:
        lever_list.append("refusal")

    try:
        task = scaffold_task(name, tier=tier.upper(), apps=app_list, levers=lever_list,
                             outcome=outcome, seed=seed, distractors=distractors)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    _stage_package(task)
    console.print(f"[green]created {task}[/green]\n")
    for f in sorted(p for p in task.rglob("*") if p.is_file() and "mcp_stump" not in p.parts):
        console.print(f"  {f.relative_to(task)}")
    console.print(f"""
[bold]next[/bold]
  1. write instruction.md      (rules are in the file; delete the notes block)
  2. fill tests/checks.py      (state paths are real; the assertions are yours)
  3. write solution/solve.py   (helpers are stubbed: call/raw/resilient)
  4. mcp-stump preflight {task}   [dim]# prove the seed has what you need[/dim]
  5. mcp-stump derive {task}      [dim]# oracle -> ground truth, + nop floor[/dim]
  6. mcp-stump run {task} -n 8
""")


@app.command()
def preflight(
    task: Path = typer.Argument(..., help="Task whose world contract to check."),
    facade: str = typer.Option("http://127.0.0.1:8199/mcp", "--facade",
                               help="A running sandbox to probe."),
) -> None:
    """Check the task's [world] contract against a live sandbox. No inference.

    A seed selects a world; it does not promise the world contains what the
    task needs. This is what makes the selection checkable -- run it before
    writing an oracle, and again before spending a pass@k.
    """
    import asyncio

    contract = load_contract(task.resolve())
    if not contract:
        console.print("[yellow]no [world] contract declared -- nothing to check.[/yellow]")
        console.print("Declare one in task.toml so a bad seed fails here, not mid-oracle.")
        raise typer.Exit(code=0)

    res = asyncio.run(do_preflight(facade, contract))
    for r in res.requirements:
        mark = "[green]ok  [/green]" if r.ok else "[red]FAIL[/red]"
        console.print(f"  {mark} {r.name:<44} {r.detail}")
    if res.ok:
        console.print(f"\n[green]world contract satisfied ({len(res.requirements)} checks)[/green]")
    else:
        console.print(f"\n[red]{len(res.failures)} requirement(s) unmet -- "
                      f"this task cannot be solved in this world.[/red]")
        raise typer.Exit(code=2)


@app.command("derive")
def derive_cmd(
    task: Path = typer.Argument(..., help="Task directory to derive ground truth for."),
    bridge: str = typer.Option(os.environ.get("CCBRIDGE_URL", "http://127.0.0.1:8765"), "--bridge"),
    keep_raw: bool = typer.Option(False, "--keep-raw", help="Keep the raw Harbor job dirs."),
    skip_nop: bool = typer.Option(False, "--skip-nop", help="Skip the nop floor check (NOT for delivery)."),
) -> None:
    """Run the oracle and generate this task's ground truth. No model inference.

    Writes initial_state.json, expected_state.json, judge_spec.json and
    gold_plan.json into tests/. Then runs nop to prove the floor: a spec that
    fails to parse scores every run 1.0, and nop is what catches it.
    """
    task = task.resolve()
    if _stage_package(task):
        console.print("[dim]staged scoring package into tests/ (was stale)[/dim]")
    meta = _read_task_meta(task)
    console.rule(f"[bold]derive {meta['name']}")
    env = _bridge_env(bridge)
    raw = task / ".derive"
    shutil.rmtree(raw, ignore_errors=True)

    console.print("[bold]oracle[/bold]")
    reward = _control(task, raw / "oracle", "oracle", env)
    oracle_dir = _harvest(raw / "oracle", raw / "harvested")
    if reward != 1.0:
        console.print(f"[red]oracle scored {reward} against the PREVIOUS spec.[/red] "
                      "Deriving anyway -- the new spec comes from its final state.")

    stats = do_derive(task, oracle_dir)
    console.print(f"  derived: [green]{stats['positive']} positive[/green], "
                  f"{stats['negative']} negative keys | {stats['plan_nodes']} plan nodes "
                  f"| {stats['trace_calls']} oracle calls")
    console.print(f"  servers: {', '.join(stats['servers'])}")

    authored = task / "tests" / "judge_spec.authored.json"
    if authored.is_file():
        from .verify.judge import JudgeSpec
        cmp = compare_authored(
            json.loads(authored.read_text()),
            JudgeSpec.from_dict(json.loads((task / "tests" / "judge_spec.json").read_text())))
        console.print(f"  authored design: {cmp['authored_positive']} positive / "
                      f"{cmp['authored_negative']} negative")
        for k in cmp["uncovered_positive"]:
            console.print(f"    [yellow]not covered by derived spec:[/yellow] {k}")
        for k in cmp["uncovered_negative"]:
            console.print(f"    [yellow]negative not covered:[/yellow] {k}")

    if not skip_nop:
        console.print("\n[bold]nop floor check[/bold]")
        nop = _control(task, raw / "nop", "nop", env)
        if nop == 0.0:
            console.print("  nop -> [green]0.0 OK[/green]  (spec is not vacuous)")
        else:
            console.print(f"  nop -> [red]{nop} FAIL -- must be 0.0.[/red] "
                          "A non-zero nop means the spec asserts nothing.")
            raise typer.Exit(code=2)

    if not keep_raw:
        shutil.rmtree(raw, ignore_errors=True)
    console.print("\n[green]ground truth written to tests/[/green]")


@app.command()
def rescore(
    trials: Path = typer.Argument(..., help="A completed out/trials_<task> directory."),
    task: Path = typer.Argument(..., help="The task it was run against."),
    check: bool = typer.Option(False, "--check", help="Report what would change; write nothing."),
    efs: Optional[Path] = typer.Option(None, "--efs", help="Equivalence sets (default registry/efs.json)."),
) -> None:
    """Recompute every scored artifact from preserved state, without re-running.

    Use after a scoring change -- a new detector, a weighting fix, a widened
    equivalence set. Everything the scorer needs was captured at run time, so
    this is a pure recomputation; re-running the model would cost money for no
    new information.

    It cannot recompute the run itself: if the sandbox changed, the preserved
    states no longer describe the environment under test and a real re-run is
    required.
    """
    res = do_rescore(trials, task, efs_path=efs, check=check)
    verb = "would change" if check else "updated"
    console.print(f"{res['runs']} run(s) rescored | EFS {res['efs_sets']} sets, "
                  f"coverage {res['efs_coverage']}")
    if not res["changed"]:
        console.print("  [green]nothing stale[/green]")
    for c in res["changed"]:
        console.print(f"  [yellow]{c['run']}[/yellow] {verb}:")
        for k, (was, now) in c["changed"].items():
            console.print(f"      {k}: {was} -> {now}")


@app.command()
def bundle(
    trials: Path = typer.Argument(..., help="A completed out/trials_<task> directory."),
    task: Path = typer.Argument(..., help="The task directory it was run against."),
    dest: Path = typer.Option(Path("delivery"), "--dest", "-d"),
) -> None:
    """Assemble the delivery bundle from a completed trials directory."""
    out = build_bundle(trials, task, dest / task.name)
    console.print(f"wrote [cyan]{out}[/cyan]")
    m = json.loads((out / "manifest.json").read_text())
    console.print(f"  task    : {m['task']['name']}  ({m['task']['capability_level']})")
    console.print(f"  levers  : {', '.join(m['task']['stump_levers'])}")
    console.print(f"  measured: p̂={m['measurement']['p_hat']} "
                  f"CI={m['measurement']['ci95']} n={m['measurement']['n']}")
    console.print(f"  bundle  : {m['bundle']['attempts']} attempts, {m['bundle']['pairs']} pairs")


def _summary_from_json(d: dict, ks: list[int]) -> TaskSummary:
    attempts = [
        AttemptResult(
            attempt=a["attempt"], passed=a["passed"],
            completion_rate=a["completion_rate"], misbehaving_rate=a["misbehaving_rate"],
            graph_f1=a["graph_f1"], reward=a["reward"], primary_mode=a["primary_mode"],
            crux_aligned=a.get("crux_aligned"), call_stats=a.get("call_stats", {}),
            usage=Usage(**{k: v for k, v in (a.get("usage") or {}).items()
                           if k in Usage.__dataclass_fields__}),
            duration_sec=a.get("duration_sec", 0.0), trajectory_path=a.get("trajectory"),
        )
        for a in d.get("attempts", [])
    ]
    return TaskSummary(
        task_name=d["task"], model=d["model"], agent=d["agent"], seed=d["seed"],
        levers=d.get("levers", []), attempts=attempts, ks=ks,
        oracle_reward=d.get("controls", {}).get("oracle_reward"),
        nop_reward=d.get("controls", {}).get("nop_reward"),
    )


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

def _report_controls(oracle: float | None, nop: float | None) -> None:
    ok_o = oracle == 1.0
    ok_n = nop == 0.0
    console.print(f"  oracle -> {oracle}  {'[green]ok[/green]' if ok_o else '[red]FAIL (must be 1.0)[/red]'}")
    console.print(f"  nop    -> {nop}  {'[green]ok[/green]' if ok_n else '[red]FAIL (must be 0.0)[/red]'}")


def _print_attempt(r: AttemptResult) -> None:
    mark = "[green]pass[/green]" if r.passed else "[red]fail[/red]"
    console.print(
        f"  {r.attempt:>2}. {mark}  Rc={r.completion_rate:.2f} Rb={r.misbehaving_rate:.2f} "
        f"F1={r.graph_f1:.2f}  {r.primary_mode}"
    )


def _print_summary(s: TaskSummary, ks: list[int]) -> None:
    m = s.metrics()
    t = Table(title="metrics", show_header=True, header_style="bold")
    t.add_column("k")
    t.add_column("pass@k", justify="right")
    t.add_column("pass^k", justify="right")
    for k in ks:
        t.add_row(str(k), _fmt(m.get(f"pass@{k}")), _fmt(m.get(f"pass^{k}")))
    console.print(t)
    console.print(f"  p̂ = {m['p_hat']}  CI95 = {m['ci95']}  (n={m['n']}, c={m['c']})")

    v = s.validity()
    if v["admissible"]:
        console.print("  [green]admissible[/green]")
    else:
        console.print("  [red]NOT admissible[/red]")
        for p in v["problems"]:
            console.print(f"    - {p}")

    u = s.usage()
    if u.get("measured_attempts"):
        console.print(
            f"  cost: ${u['total_cost_usd']:.4f} total, ${u['mean_cost_usd']:.4f}/attempt"
            + (f", ${u['cost_per_solve_usd']:.4f}/solve" if u.get("cost_per_solve_usd") else "")
        )
        share, cache = u.get("prompt_share_of_tokens"), u.get("cache_hit_rate")
        detail = ""
        if share is not None:
            detail = f"  (prompt {share:.1%} of total"
            detail += f", cache hit {cache:.1%})" if cache is not None else ")"
        console.print(
            f"  tokens: {u['total_input_tokens']:,} in / "
            f"{u['total_output_tokens']:,} out{detail}"
        )

    fb = s.failure_breakdown()
    if fb:
        console.print("  failures: " + ", ".join(f"{k}={v}" for k, v in fb.items()))


def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.3f}"


if __name__ == "__main__":
    app()
