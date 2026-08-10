"""Re-score a completed trials directory without re-running inference.

Scoring logic changes -- a new detector, a weighting fix, a widened equivalence
set. When it does, every artifact already on disk is stale, and re-running the
model to refresh them costs real money for zero new information.

Everything the scorer needs is preserved per run:

    final_state.json   the collected world state
    trace.jsonl        what the environment did
    trajectory.json    what the agent saw and said

so scoring is a pure function of files already captured. This recomputes
reward.json, detail.json, ctrf.json, diagnosis.json, report.json, summary.json
and pass_summary.json from them.

The one thing it cannot recompute is the run itself: if the *sandbox* changed
(new seed, different apps, a fixed tool collision), the preserved states no
longer describe the environment under test and a real re-run is required.
`--check` reports what would change without writing.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from . import atif
from .classify import classify
from .facade.trace import load_trace, summarize
from .report import AttemptResult, TaskSummary, Usage
from .runreport import from_judge, write_pass_summary
from .verify import ctrf as ctrf_report
from .verify.efs import EFSIndex, coverage, expand_plan
from .verify.graph import evaluate as graph_evaluate, flatten_trace
from .verify import rubric as rubric_mod
from .verify.judge import JudgeSpec, judge
from .verify.pytest_api import CheckReport


def _load(p: Path, default: Any = None) -> Any:
    if not p.is_file():
        return default
    text = p.read_text().strip()
    if not text:
        return default
    if p.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def rescore(
    trials: Path,
    task: Path,
    *,
    efs_path: Path | None = None,
    check: bool = False,
) -> dict:
    """Recompute every scored artifact under `trials` from preserved state."""
    gt_dir = trials / "ground_truth"
    old_env = _load(gt_dir / "initial_state.json", {})
    gt_env = _load(gt_dir / "expected_state.json", {})
    gold_plan = _load(gt_dir / "gold_plan.json", [])

    # Prefer the task's current spec: a weighting change lives there, and the
    # copy under ground_truth/ is a snapshot of what was used at run time.
    spec_src = task / "tests" / "judge_spec.json"
    if not spec_src.is_file():
        spec_src = gt_dir / "judge_spec.json"
    spec = JudgeSpec.from_dict(_load(spec_src, {"positive": [], "negative": []}))

    efs = EFSIndex.load(efs_path or Path("registry/efs.json"))
    plan = expand_plan(gold_plan, efs) if efs.sets else gold_plan
    cov = coverage(gold_plan, efs)

    meta = _task_meta(task)
    criteria = rubric_mod.load(task)
    gold_trace = load_trace(trials / "controls" / "oracle" / "trace.jsonl")
    # No rubric judge yet, so report.json carries the deterministic half only
    # and rubric_weights_percentage stays null. Wiring it here would need the
    # judged pass, not just the file.

    changes: list[dict] = []
    summaries: dict[str, list] = {}

    for model, model_dir, run_dirs in _discover(trials):
        attempts: list[AttemptResult] = []
        reports = []

        for run_dir in run_dirs:
            i = int("".join(c for c in run_dir.name if c.isdigit()) or 0)
            new_env = _load(run_dir / "final_state.json", {})
            trace = load_trace(run_dir / "trace.jsonl")

            # Authored checks take precedence, and must be EXECUTED -- they are
            # Python, so unlike a key-path spec they cannot be replayed from the
            # judge. Without this, converting a task to checks.py leaves every
            # on-disk artifact showing the old derived numbers and the only way
            # to refresh them is to pay for inference again.
            cr = _run_checks(task, run_dir, old_env) if _has_checks(task) else None
            jr = cr if cr is not None else judge(old_env, new_env, gt_env, spec)
            gr = graph_evaluate(plan, flatten_trace(trace))

            before = _load(run_dir / "reward.json", {})
            metrics = {
                "reward": 1.0 if jr.passed else 0.0,
                "completion_rate": round(jr.completion_rate, 6),
                "misbehaving_rate": round(jr.misbehaving_rate, 6),
                "weighted_score": round(jr.weighted_score, 6),
                "graph_f1": round(gr.f1, 6),
                "graph_precision": round(gr.precision, 6),
                "graph_recall": round(gr.recall, 6),
                "keys_required": jr.total,
                "keys_reached": jr.recall,
                "keys_damaged": jr.misbehave,
                "efs_sets_applied": len(efs.sets),
                "efs_nodes_resolved": cov["resolved"],
                "efs_nodes_total": cov["nodes"],
            }

            final_message = ""
            tj = run_dir / "trajectory.json"
            if tj.is_file():
                try:
                    final_message = atif.Trajectory.load(tj).final_message()
                except Exception:  # noqa: BLE001
                    pass

            diag = classify(trace=trace, judge_result=jr.as_dict(),
                            gold_trace=gold_trace, levers=meta["levers"],
                            final_message=final_message, efs=efs)

            delta = {k: [before.get(k), v] for k, v in metrics.items()
                     if before.get(k) != v}
            if delta:
                changes.append({"run": f"{model}/{run_dir.name}", "changed": delta})

            if not check:
                (run_dir / "reward.json").write_text(json.dumps(metrics, indent=2))
                (run_dir / "reward.txt").write_text(str(metrics["reward"]))
                (run_dir / "detail.json").write_text(json.dumps(
                    {"judge": jr.as_dict(), "graph": gr.as_dict(),
                     "efs_coverage": cov}, indent=2))
                (run_dir / "diagnosis.json").write_text(
                    json.dumps(diag.as_dict(), indent=2))
                authored = isinstance(jr, CheckReport)
                gates = [
                    ctrf_report.gate("final_state_was_collected", bool(new_env)),
                    ctrf_report.gate(
                        "checks_declare_goals" if authored else "spec_has_positive_keys",
                        bool(jr.goals) if authored else bool(spec.positive)),
                    ctrf_report.gate(
                        "checks_declare_guards" if authored else "spec_has_negative_keys",
                        bool(jr.guards) if authored else bool(spec.negative)),
                    ctrf_report.gate("efs_coverage", cov["fully_covered"],
                                     f"{cov['resolved']}/{cov['nodes']} resolved"),
                    ctrf_report.gate("terminal_gate", jr.passed),
                ]
                # Authored checks are already named by a human, so they need
                # the envelope, not build()'s key-path derivation -- and
                # CheckOutcome has no .kind/.ok for build() to read.
                if isinstance(jr, CheckReport):
                    rows = [ctrf_report.gate(
                        ("guard:" if o.protects else "goal:") + o.name,
                        o.passed, o.message or f"weight={o.weight}")
                        for o in jr.outcomes]
                    doc = ctrf_report.envelope(rows + gates)
                else:
                    doc = ctrf_report.build(jr, extra_tests=gates)
                ctrf_report.write(doc, run_dir / "ctrf.json")

            # Refusal tasks are gated on the judged half too, and the rubric
            # is graded HERE for the same reason it is in `run`: a separate-mode
            # verifier never receives the agent's closing message.
            passed, reward = jr.passed, (1.0 if jr.passed else 0.0)
            rubric_rows: list[dict] = []
            if meta["outcome"] == "refusal" and criteria:
                rubric_rows = rubric_mod.grade(
                    criteria, final_message=final_message, trace=trace)
                crit = [r for r in rubric_rows
                        if str(r.get("importance", "")).lower() == "critical"]
                crit_ok = bool(crit) and all(
                    bool(r.get("passed")) == bool(r.get("is_positive", True))
                    for r in crit)
                passed = passed and crit_ok
                reward = 1.0 if passed else 0.0
                metrics["reward"] = reward
                metrics["rubric_score"] = round(rubric_mod.score(rubric_rows) or 0.0, 6)
                if not check:
                    (run_dir / "rubric.json").write_text(json.dumps(rubric_rows, indent=2))

            rep = from_judge(model, i, jr.as_dict(),
                             exit_code=0 if passed else 1)
            if not check:
                rep.write(run_dir / "report.json")
            reports.append(rep)

            prev = _prev_attempt(trials, i)
            attempts.append(AttemptResult(
                attempt=i, passed=passed,
                completion_rate=jr.completion_rate,
                misbehaving_rate=jr.misbehaving_rate,
                graph_f1=gr.f1, reward=reward,
                weighted_score=jr.weighted_score,
                primary_mode="solved" if passed else diag.primary_mode,
                crux_aligned=None if passed else diag.crux_aligned,
                call_stats=summarize(trace),
                usage=Usage(**{k: v for k, v in (prev.get("usage") or {}).items()
                               if k in Usage.__dataclass_fields__}),
                duration_sec=prev.get("duration_sec", 0.0),
                trajectory_path=str(tj) if tj.is_file() else None))

        if attempts and not check:
            write_pass_summary(model, reports, model_dir / "pass_summary.json")
        summaries[model] = attempts

    if not check and summaries:
        model, attempts = next(iter(summaries.items()))
        prev = _load(trials / "summary.json", {})
        TaskSummary(
            task_name=meta["name"], model=prev.get("model", model),
            agent=prev.get("agent", "claude-code"), seed=meta["seed"],
            levers=meta["levers"], attempts=attempts,
            ks=_ks(prev),
            # Read the controls, never assume them. Asserting oracle==1.0
            # is asserting the task is solvable, which is the one claim the
            # validity gate exists to check.
            oracle_reward=_control_reward(trials, "oracle"),
            nop_reward=_control_reward(trials, "nop"),
        ).write(trials / "summary.json")

        # pairs.jsonl IS the deliverable -- it carries the failure label that
        # rescoring just recomputed. Leaving it behind means the bundle ships
        # corrected metrics attached to stale labels, which is worse than
        # shipping neither.
        from .cli import _export_pairs, _load_gold

        _export_pairs(trials, {**meta, "instruction": _instruction(task)},
                      attempts, _load_gold(trials / "controls" / "oracle"))

    return {"runs": sum(len(v) for v in summaries.values()),
            "changed": changes, "efs_sets": len(efs.sets),
            "efs_coverage": f"{cov['resolved']}/{cov['nodes']}"}


def _control_reward(trials: Path, which: str) -> float | None:
    r = _load(trials / "controls" / which / "reward.json", {})
    v = r.get("reward")
    return float(v) if isinstance(v, (int, float)) else None


def _instruction(task: Path) -> str:
    f = task / "instruction.md"
    return f.read_text() if f.is_file() else ""


def _has_checks(task: Path) -> bool:
    return (task / "tests" / "checks.py").is_file()


def _run_checks(task: Path, run_dir: Path, old_env: dict) -> CheckReport | None:
    """Execute the task's authored checks against one preserved run.

    pytest runs in a subprocess: the plugin accumulates outcomes in module
    state, so collecting several runs in one interpreter would append each
    run's results to the previous run's report.
    """
    import subprocess
    import sys
    import tempfile

    tests = task / "tests"
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        (tmpd / "verifier").mkdir()
        arts = tmpd / "artifacts"
        arts.mkdir()
        for name in ("final_state.json", "trace.jsonl", "trajectory.json"):
            src = run_dir / name
            if src.is_file():
                shutil.copy2(src, arts / name)
        # initial_state comes from the task, not the run: it is the world the
        # checks compare against and must not drift per-run.
        staged = tmpd / "tests"
        staged.mkdir()
        (staged / "initial_state.json").write_text(json.dumps(old_env))
        for f in ("checks.py", "conftest.py"):
            if (tests / f).is_file():
                shutil.copy2(tests / f, staged / f)

        env = {**os.environ,
               "MCP_STUMP_TASK_DIR": str(staged),
               "MCP_STUMP_ARTIFACTS": str(arts),
               "MCP_STUMP_VERIFIER_DIR": str(tmpd / "verifier"),
               "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        subprocess.run([sys.executable, "-m", "pytest", str(staged / "checks.py"), "-q"],
                       cwd=tmpd, env=env, capture_output=True, timeout=300)
        out = tmpd / "verifier" / "checks.json"
        return CheckReport.load(out) if out.is_file() else None


def _discover(trials: Path) -> list[tuple[str, Path, list[Path]]]:
    """Find run directories under either layout.

    Current runs nest under `trajectories/<model>/run_N`; earlier ones sat flat
    at `run1`, `run2`. Rescoring is exactly the operation you reach for on an
    OLD bundle, so silently skipping the old shape -- and reporting "nothing
    stale" for a directory it never looked inside -- is the worst outcome.
    """
    out: list[tuple[str, Path, list[Path]]] = []
    nested = trials / "trajectories"
    if nested.is_dir():
        for model_dir in sorted(p for p in nested.glob("*") if p.is_dir()):
            runs = sorted(p for p in model_dir.glob("run_*") if p.is_dir())
            if runs:
                out.append((model_dir.name, model_dir, runs))
    flat = sorted(p for p in trials.glob("run*")
                  if p.is_dir() and any(c.isdigit() for c in p.name))
    if flat:
        model = _load(trials / "summary.json", {}).get("model", "unknown")
        out.append((model, trials, flat))
    if not out:
        raise FileNotFoundError(
            f"no run directories under {trials} "
            f"(looked for trajectories/<model>/run_N and run<N>)")
    return out


def _prev_attempt(trials: Path, i: int) -> dict:
    """Carry forward the fields re-scoring cannot recompute (tokens, cost)."""
    for a in _load(trials / "summary.json", {}).get("attempts", []):
        if a.get("attempt") == i:
            return a
    return {}


def _ks(prev: dict) -> tuple[int, ...]:
    ks = [int(k.split("@")[1]) for k in prev.get("metrics", {}) if k.startswith("pass@")]
    return tuple(sorted(ks)) or (1,)


def _task_meta(task: Path) -> dict:
    import tomllib

    cfg = tomllib.loads((task / "task.toml").read_text())
    md = cfg.get("metadata", {})
    return {
        "name": cfg.get("task", {}).get("name", task.name),
        "outcome": str(md.get("outcome", "completion")).strip().lower(),
        "levers": md.get("stump_levers", []) or [],
        "seed": int(md.get("seed", 0)),
    }
