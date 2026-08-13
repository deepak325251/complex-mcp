from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.classify_failure import classify, parse_expected_tools  # noqa: E402
from benchmark.passk import estimate as _passk_estimate  # noqa: E402
from benchmark.atif import from_complexmcp as _atif_from_complexmcp  # noqa: E402
from benchmark.mcp_traj import from_complexmcp as _msg_traj_from_complexmcp  # noqa: E402


_TOOL_RE = re.compile(r"<tool>\s*(\{.*?\})\s*</tool>", re.DOTALL)
_RESP_RE = re.compile(r"<response>\s*(.*?)\s*</response>", re.DOTALL)
# Real extended-thinking, emitted by the agent as a self-delimiting block with an
# optional signature attribute. Split out so `reasoning` carries the model's true
# thinking and `message` carries its visible speech -- the two used to be merged.
_THINK_RE = re.compile(r'<thinking(?:\s+signature="([^"]*)")?\s*>(.*?)</thinking>', re.DOTALL)

# Backend control/format sentinels that leak from the (redacted) thinking channel
# into the visible-text stream -- e.g. a stray `end_turn` token glued onto prose
# (`...boundary.\nendturnLet me...`) or an `_input=...` scaffold prefix. They are
# never real assistant speech, so strip them from the visible message before it
# is recorded, rather than letting the garble land in the trace.
_LEAK_RE = re.compile(r'_input=\.+|\bend_?turn')


def _rubric_rc_rb(rubric_result: dict | None):
    """Return (Rc, Rb) for a rubric result.

    Rc (completion) is derived from per_criterion when the grader leaves it null:
    positive criteria (weight > 0) count toward Rc when satisfied. That polarity
    is consistent -- a positive criterion "satisfied" always means completed.

    Rb (misbehavior) is NOT derived here. Guard criteria are phrased
    inconsistently -- some describe the DEFECT ("claims to have bought another
    item"; satisfied==True means the bad thing happened) and some describe the
    SAFE behavior ("does NOT falsely claim completion"; satisfied==True means
    good). So `satisfied` + weight-sign cannot tell a HIT from a hold, and any
    heuristic yields a misleading Rb (e.g. a benign run scoring rb=1.0). We
    surface only the grader's own Rb; else None, with the raw per_criterion left
    for a human/grader to interpret.
    """
    if not rubric_result:
        return None, None
    rc, rb = rubric_result.get("rc"), rubric_result.get("rb")
    if rc is not None or rb is not None:
        return rc, rb
    crit = rubric_result.get("per_criterion") or []
    if not crit:
        return None, None
    pos_total = pos_hit = 0.0
    for c in crit:
        w = c.get("score") or 0
        # Guard criteria (is_positive: false, or a negative score) are NOT part
        # of the completion denominator -- counting them capped a clean run's Rc
        # (e.g. 5/19 instead of 5/10). Only positive criteria define Rc.
        is_pos = c.get("is_positive")
        guard = (is_pos is False) or (is_pos is None and w < 0)
        if not guard and w > 0:
            pos_total += w
            if c.get("satisfied"):
                pos_hit += w
    rc = round(pos_hit / pos_total, 6) if pos_total else None
    # Rb stays with the grader; never guessed from guard phrasing.
    return rc, None


def _split_thinking(span: str):
    """Return (thinking_text, visible_message, signatures) for a pre-tool span."""
    thoughts, sigs = [], []
    for m in _THINK_RE.finditer(span):
        t = (m.group(2) or "").strip()
        if not t:
            # Drop empty thinking blocks entirely -- a signature must never
            # survive without the reasoning text it vouches for (that orphan
            # pairing was the original "signature but fake reasoning" bug).
            continue
        thoughts.append(t)
        if m.group(1):
            sigs.extend(s for s in m.group(1).split(",") if s)
    message = _THINK_RE.sub("", span)
    message = _LEAK_RE.sub("", message).strip()
    return "\n\n".join(thoughts), message, sigs


def _slug(name: str, maxlen: int = 40) -> str:
    core = re.sub(r"^complexmcp-l\d+-s\d+-", "", name)
    core = re.sub(r"-\d{3}$", "", core)
    core = re.sub(r"[^A-Za-z0-9]+", "-", core).strip("-").lower()
    return core[:maxlen] or "task"


def parse_trajectory(output: str) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    pos = 0
    step_no = 0
    while True:
        tm = _TOOL_RE.search(output, pos)
        if not tm:
            break
        step_no += 1
        # `reasoning` is now the model's REAL thinking (from <thinking> blocks);
        # `message` is its visible speech before the tool call. Previously the
        # whole span was labeled "reasoning", so visible text posed as thinking.
        reasoning, message, signature = _split_thinking(output[pos:tm.start()])
        tool_json = tm.group(1)
        try:
            tool_data = json.loads(tool_json)
            tool_name = tool_data.get("name")
            tool_args = tool_data.get("arguments", {})
        except json.JSONDecodeError:
            tool_name = None
            tool_args = tool_json

        rm = _RESP_RE.search(output, tm.end())
        if rm and rm.start() - tm.end() < 80:
            response_raw = rm.group(1)
            try:
                response: Any = json.loads(response_raw)
            except json.JSONDecodeError:
                response = response_raw
            pos = rm.end()
        else:
            response = None
            pos = tm.end()

        steps.append({
            "step": step_no,
            "reasoning": reasoning,
            "message": message,
            "signature": signature,
            "tool": tool_name,
            "arguments": tool_args,
            "response": response,
        })
    # Strip any trailing thinking block from the final visible message too.
    _, final_message, _ = _split_thinking(output[pos:])
    return {"steps": steps, "final_message": final_message}


def render_output_md(record: dict, traj: dict) -> str:
    lines = [
        f"# Task {record['index']}: {record['name']}",
        "",
        f"- **Query**: {record['query']}",
        f"- **Seed**: {record['seed']}",
        f"- **Apps**: {', '.join(record.get('apps', []))}",
        f"- **Level**: {record.get('level')}",
        f"- **Tool calls**: valid={record['valid_tool_calls']} "
        f"invalid={record['invalid_tool_calls']} error={record['error_tool_calls']}",
        f"- **Tokens**: prompt={record['tokens'].get('prompt')} "
        f"llm={record['tokens'].get('llm')} tool={record['tokens'].get('tool')}",
        "",
        "---",
        "",
        f"## Trajectory ({len(traj['steps'])} tool calls)",
        "",
    ]
    for s in traj["steps"]:
        if s.get("reasoning"):
            lines += [f"### Step {s['step']} — thinking", "", s["reasoning"], ""]
        if s.get("message"):
            lines += [f"### Step {s['step']} — message", "", s["message"], ""]
        lines += [
            f"### Step {s['step']} — call `{s['tool']}`",
            "",
            "```json",
            json.dumps(s["arguments"], indent=2, ensure_ascii=False),
            "```",
            "",
            f"### Step {s['step']} — response",
            "",
            "```json",
            json.dumps(s["response"], indent=2, ensure_ascii=False)
                if not isinstance(s["response"], str) else s["response"],
            "```",
            "",
        ]
    if traj["final_message"]:
        lines += ["## Final message", "", traj["final_message"], ""]
    return "\n".join(lines)


def write_task_dir(tasks_root: Path, record: dict, *,
                   score: dict | None = None,
                   task_context: dict | None = None) -> tuple[Path, dict]:
    slug = _slug(record["name"])
    task_dir = tasks_root / f"task_{record['index']:03d}__{slug}"
    task_dir.mkdir(parents=True, exist_ok=True)

    meta = {k: record[k] for k in ("index", "name", "query", "seed", "apps", "level")}
    (task_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    traj = parse_trajectory(record.get("output", ""))
    (task_dir / "trajectory.json").write_text(json.dumps(traj, indent=2, ensure_ascii=False))
    (task_dir / "output.md").write_text(render_output_md(record, traj))

    tool_summary = {
        "tool_cnt": record.get("tool_cnt", {}),
        "valid_tool_calls": record["valid_tool_calls"],
        "invalid_tool_calls": record["invalid_tool_calls"],
        "error_tool_calls": record["error_tool_calls"],
    }
    (task_dir / "tool_summary.json").write_text(json.dumps(tool_summary, indent=2))
    (task_dir / "tokens.json").write_text(json.dumps(record.get("tokens", {}), indent=2))

    if score is None:
        score = {
            "gradeable": False,
            "reason": "Harbor tasks in benchmark/harbor_final_all/ have no gt_env.json "
                      "(needs tests/gen_gt.py replay of solution/trajectory.json).",
            "reward": None,
            "recall": None,
            "misbehave": None,
            "total": None,
        }

    passed = bool(score.get("passed", False))
    if not passed:
        ctx = dict(task_context or {})
        if "expected_tools" not in ctx and record.get("expected_tool_calls"):
            ctx["expected_tools"] = parse_expected_tools(record.get("expected_tool_calls"))
        verdict = classify(
            trajectory=traj,
            tool_summary=tool_summary,
            score=score,
            task_context=ctx,
            final_message=traj.get("final_message"),
        )
        score = {**score, **verdict.to_dict()}

    (task_dir / "score.json").write_text(json.dumps(score, indent=2))

    return task_dir, score


def _mcp_stump_slug(name: str) -> str:
    if name.startswith("mcp-stump/"):
        return name.split("/", 1)[1]
    return name


def _next_run_number(model_dir: Path) -> int:
    if not model_dir.exists():
        return 1
    existing = [d.name for d in model_dir.iterdir()
                if d.is_dir() and d.name.startswith("run_")]
    nums = []
    for n in existing:
        try:
            nums.append(int(n.split("_", 1)[1]))
        except (IndexError, ValueError):
            continue
    return (max(nums) + 1) if nums else 1


_GT_FILES = (
    "expected_state.json",
    "gold_plan.json",
    "initial_state.json",
    "judge_spec.json",
    "gt_env.json",
)


def _write_ground_truth(trials_dir: Path, task_dir_source: str | Path | None) -> None:
    if not task_dir_source:
        return
    tests_dir = Path(task_dir_source) / "tests"
    if not tests_dir.exists():
        return
    gt_dir = trials_dir / "ground_truth"
    for name in _GT_FILES:
        src = tests_dir / name
        if not src.exists():
            continue
        gt_dir.mkdir(parents=True, exist_ok=True)
        dest = gt_dir / name
        if not dest.exists():
            dest.write_text(src.read_text())


def _write_rubric_json(run_dir: Path, rubric_result: dict | None) -> None:
    if not rubric_result:
        return
    (run_dir / "rubric.json").write_text(
        json.dumps(rubric_result, indent=2, ensure_ascii=False, default=str)
    )


def _write_detail_json(run_dir: Path, score: dict, rubric_result: dict | None,
                       tool_summary: dict) -> None:
    detail = {
        "reward": score.get("reward"),
        "recall": score.get("recall"),
        "total": score.get("total"),
        "misbehave": score.get("misbehave"),
        "passed": bool(score.get("passed")),
        "gradeable": bool(score.get("gradeable")),
        "passed_tests": score.get("passed_tests"),
        "tool_summary": tool_summary,
    }
    if rubric_result:
        detail["rubric"] = {
            "format": rubric_result.get("format"),
            "rubric_score": rubric_result.get("rubric_score"),
            "rc": rubric_result.get("rc"),
            "rb": rubric_result.get("rb"),
            "passed": rubric_result.get("passed"),
            "per_check": rubric_result.get("per_check"),
            "per_criterion": rubric_result.get("per_criterion"),
        }
    pytest_checks = score.get("pytest_checks")
    if pytest_checks:
        detail["pytest_checks"] = pytest_checks
    (run_dir / "detail.json").write_text(
        json.dumps(detail, indent=2, ensure_ascii=False, default=str)
    )


def _write_ctrf_json(run_dir: Path, task_name: str, model: str, run_no: int,
                     score: dict, rubric_result: dict | None) -> None:
    from datetime import datetime, timezone
    passed = bool(score.get("passed"))
    tests = [{
        "name": f"{task_name}#reward",
        "status": "passed" if passed else "failed",
        "duration": 0,
    }]
    if rubric_result and "per_criterion" in rubric_result:
        for c in rubric_result["per_criterion"]:
            tests.append({
                "name": f"{task_name}#rubric.{c.get('number')}",
                "status": "passed" if c.get("satisfied") else "failed",
                "duration": 0,
                "message": c.get("justification", ""),
            })
    elif rubric_result and "per_check" in rubric_result:
        for c in rubric_result["per_check"]:
            tests.append({
                "name": f"{task_name}#rubric.{c.get('check_id')}",
                "status": "passed" if c.get("passed") else "failed",
                "duration": 0,
                "message": c.get("reason", ""),
            })
    for tname, ok in (score.get("passed_tests") or {}).items():
        tests.append({
            "name": f"{task_name}#pytest.{tname}",
            "status": "passed" if ok else "failed",
            "duration": 0,
        })
    # State-diff per-key-path granularity (judge_spec allowlist). Each scored
    # key-path gets its own CTRF row so a failing path is legible instead of
    # hidden behind the single #reward aggregate. Positive paths => goal checks;
    # negative paths => @protects checks.
    def _dot(path) -> str:
        return ".".join(str(p) for p in path)
    for o in (score.get("passed_positive") or []):
        tests.append({
            "name": f"{task_name}#state.{_dot(o['path'])}",
            "status": "passed", "duration": 0,
        })
    for o in (score.get("failed_positive") or []):
        tests.append({
            "name": f"{task_name}#state.{_dot(o['path'])}",
            "status": "failed", "duration": 0,
            "message": f"expected={o.get('expected')!r} got={o.get('new')!r}",
        })
    for o in (score.get("held_negative") or []):
        tests.append({
            "name": f"{task_name}#protect.{_dot(o['path'])}",
            "status": "passed", "duration": 0,
        })
    for o in (score.get("damaged_negative") or []):
        tests.append({
            "name": f"{task_name}#protect.{_dot(o['path'])}",
            "status": "failed", "duration": 0,
            "message": f"protected path changed: {o.get('old')!r} -> {o.get('new')!r}",
        })
    summary_passed = sum(1 for t in tests if t["status"] == "passed")
    ctrf = {
        "results": {
            "tool": {"name": "complexmcp-benchmark"},
            "summary": {
                "tests": len(tests),
                "passed": summary_passed,
                "failed": len(tests) - summary_passed,
                "pending": 0, "skipped": 0, "other": 0,
                "start": 0,
                "stop": int(datetime.now(timezone.utc).timestamp()),
            },
            "tests": tests,
            "extra": {"task": task_name, "model": model, "attempt": run_no},
        }
    }
    (run_dir / "ctrf.json").write_text(
        json.dumps(ctrf, indent=2, ensure_ascii=False, default=str)
    )


def write_mcp_stump_run(output_root: Path, record: dict, *,
                        model: str, score: dict | None = None,
                        task_context: dict | None = None,
                        rubric_result: dict | None = None,
                        task_dir_source: str | Path | None = None) -> tuple[Path, dict]:
    slug = _mcp_stump_slug(record["name"])
    trials_dir = output_root / f"trials_{slug}"
    model_dir = trials_dir / "trajectories" / model
    run_no = _next_run_number(model_dir)
    run_dir = model_dir / f"run_{run_no}"
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_ground_truth(trials_dir, task_dir_source)

    # Single trajectory of record: the ATIF-v1.7 delivery copy at
    # agent/trajectory.json (the shape SFT/RL tooling reads). The native
    # {steps, final_message} shape is still parsed in-memory below to build ATIF
    # + trace.jsonl, but is no longer written to disk -- nothing read it back and
    # it was a superset-duplicate of the ATIF file.
    traj = parse_trajectory(record.get("output", ""))
    atif_doc = _atif_from_complexmcp(traj, agent="complexmcp", model=model,
                                     usage=record.get("usage"),
                                     query=record.get("query", ""))
    # Thinking signatures are attached inside _atif_from_complexmcp, per step,
    # straight from the <thinking> blocks -- so a signature rides only on a step
    # that actually captured real reasoning text (no orphan-signature drift).
    atif_dir = run_dir / "agent"
    atif_dir.mkdir(parents=True, exist_ok=True)
    (atif_dir / "trajectory.json").write_text(
        json.dumps(atif_doc, indent=2, ensure_ascii=False, default=str))

    # Message-based golden trajectory (session_id/meta_info/typed content
    # blocks/turn_index) for cross-task analytics. Emitted alongside ATIF -- the
    # two are different downstream contracts, not duplicates of one shape.
    msg_traj_doc = _msg_traj_from_complexmcp(
        traj,
        task_id=record.get("name", ""),
        query=record.get("query", ""),
        taxonomy_l1=str(record.get("level", "") or ""),
        taxonomy_l2=str(record.get("taxonomy_l2", "") or ""),
        model=model,
        tokens=record.get("tokens"),
        usage=record.get("usage"),
    )
    (atif_dir / "trajectory.messages.json").write_text(
        json.dumps(msg_traj_doc, indent=2, ensure_ascii=False, default=str))

    (run_dir / "agent.log").write_text(record.get("output", ""))

    (run_dir / "initial_state.json").write_text(
        json.dumps(record.get("old_env") or {}, indent=2, ensure_ascii=False, default=str))
    (run_dir / "final_state.json").write_text(
        json.dumps(record.get("new_env") or {}, indent=2, ensure_ascii=False, default=str))

    # One JSON object per tool call (name/arguments/response), the JSONL trace
    # stream factual rubric + authored checks read. Was previously written empty,
    # which silently read as "no tool activity" to every trace-based criterion.
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(s, ensure_ascii=False, default=str)
                  for s in traj.get("steps", [])))

    if score is None:
        score = {
            "gradeable": False, "reward": None,
            "recall": None, "misbehave": None, "total": None,
        }

    passed = bool(score.get("passed", False))
    tool_summary = {
        "tool_cnt": record.get("tool_cnt", {}),
        "valid_tool_calls": record["valid_tool_calls"],
        "invalid_tool_calls": record["invalid_tool_calls"],
        "error_tool_calls": record["error_tool_calls"],
    }
    if not passed:
        ctx = dict(task_context or {})
        if "expected_tools" not in ctx and record.get("expected_tool_calls"):
            ctx["expected_tools"] = parse_expected_tools(record.get("expected_tool_calls"))
        verdict = classify(
            trajectory=traj,
            tool_summary=tool_summary,
            score=score,
            task_context=ctx,
            final_message=traj.get("final_message"),
        )
        score = {**score, **verdict.to_dict()}

    reward = score.get("reward")
    reward_val = float(reward) if reward is not None else 0.0
    (run_dir / "reward.json").write_text(json.dumps({
        "reward": reward_val,
        "total": score.get("total"),
        "recall": score.get("recall"),
        "misbehave": score.get("misbehave"),
    }, indent=2))
    (run_dir / "reward.txt").write_text(f"{reward_val}\n")

    (run_dir / "diagnosis.json").write_text(json.dumps({
        "failure_class": score.get("failure_class"),
        "reason": score.get("reason"),
        "evidence": score.get("evidence"),
    }, indent=2, ensure_ascii=False))

    total = score.get("total") or 0
    recall = score.get("recall") or 0
    misbehave = score.get("misbehave") or 0
    completion_rate = (recall / total) if total else (1.0 if passed else 0.0)
    misbehaving_rate = (misbehave / total) if total else 0.0
    pytest_checks = score.get("pytest_checks")
    channel_a_present = pytest_checks is not None
    # test_weights_percentage: 0.0 when Channel A ran and scored zero, null ONLY
    # when the channel is absent -- `channel_a_present` removes the null/0.0
    # ambiguity for downstream mean-score math.
    test_weights_percentage = (
        float(pytest_checks.get("weighted_score", 0.0)) * 100.0
        if channel_a_present else None
    )
    rubric_weights_percentage = (
        float(rubric_result.get("rubric_score", 0.0)) * 100.0
        if rubric_result else None
    )
    # Rc/Rb are only auto-filled by the predicate-style rubric; the criteria
    # (LLM-judged) format leaves them null. Derive them from per_criterion via
    # the documented formula (rubric_judge.py) so report.json carries the
    # criterion-level breakdown instead of a bare null.
    rubric_rc, rubric_rb = _rubric_rc_rb(rubric_result)
    (run_dir / "report.json").write_text(json.dumps({
        "task": record["name"],
        "model": model,
        "seed": record.get("seed"),
        "attempt": run_no,
        "passed": passed,
        "reward": reward_val,
        # final_score is the composite actually used to rank this run, so a
        # leaderboard can sort off report.json alone (no cross-file join).
        "final_score": reward_val,
        # Never hardcode a blend that didn't run: prefer the grader's own label,
        # else name the channels that actually contributed (score["basis"]).
        "final_score_basis": (
            score.get("grader")
            or ("+".join(score["basis"]) if score.get("basis") else "unknown")
        ),
        # State-diff surface (recall/misbehave over scored key-paths). The rubric
        # surface rides alongside as `rubric_rb`, NOT under the same name.
        "completion_rate": completion_rate,
        "misbehaving_rate": misbehaving_rate,
        "channel_a_present": channel_a_present,
        "test_weights_percentage": test_weights_percentage,
        "rubric_weights_percentage": rubric_weights_percentage,
        "rubric_rc": rubric_rc,
        "rubric_rb": rubric_rb,
        "rubric_per_criterion": rubric_result.get("per_criterion") if rubric_result else None,
        "tokens": record.get("tokens", {}),
        "tool_summary": tool_summary,
        # Why the episode ended: end_tag (agent emitted [END]), no_tool_calls
        # (consecutive turns with no call), or max_turns (turn/budget exhaustion).
        # Distinguishes a clean finish from a forced cutoff at 510k-token runs.
        "termination_reason": record.get("termination_reason"),
    }, indent=2, ensure_ascii=False))

    _write_rubric_json(run_dir, rubric_result)
    _write_detail_json(run_dir, score, rubric_result, tool_summary)
    _write_ctrf_json(run_dir, record["name"], model, run_no, score, rubric_result)

    return run_dir, score


def write_trials_aggregate(output_root: Path, task_name: str, model: str,
                           run_records: list[dict], *,
                           instruction: str | None = None,
                           at: list[int] | None = None,
                           controls: dict | None = None,
                           trajectory_root: Path | None = None) -> Path:
    slug = _mcp_stump_slug(task_name)
    trials_dir = output_root / f"trials_{slug}"
    trials_dir.mkdir(parents=True, exist_ok=True)

    # H5: reconcile against run_N dirs on disk. A run that hard-bounced (e.g. a
    # missing-prerequisite bounce at step 0) may never have produced a graded
    # record; counting only in-memory records silently drops it from n and the
    # failure histogram -- collapsing two distinct failure modes into one. Fold
    # any unrecorded run_N slot back in as an explicit "unrecorded_run" so the
    # denominator and taxonomy reflect what actually ran. When no root is passed,
    # auto-discover this task's own trajectories/ dir so the reconciliation is on
    # by default (no-op when the dir is absent, so existing callers are unaffected).
    if trajectory_root is None:
        _auto = trials_dir / "trajectories"
        trajectory_root = _auto if _auto.exists() else None
    if trajectory_root is not None:
        recorded = {r.get("attempt") for r in run_records if r.get("attempt")}
        run_records = list(run_records)
        for d in sorted(Path(trajectory_root).rglob("run_*")):
            if not d.is_dir():
                continue
            try:
                num = int(d.name.split("_", 1)[1])
            except (IndexError, ValueError):
                continue
            if num in recorded:
                continue
            recorded.add(num)
            run_records.append({
                "attempt": num, "passed": False,
                "failure_class": "unrecorded_run",
                "reason": (f"run_{num} present on disk but produced no graded "
                           f"record (hard bounce?); folded in so n is honest"),
            })

    n = len(run_records)
    c = sum(1 for r in run_records if r.get("passed"))
    ks = at or [1]
    # Unbiased pass@k, stability pass^k, and the Wilson CI95 on p_hat=c/n. See
    # benchmark/passk.py for why both estimators are reported.
    est = _passk_estimate(n, c, ks)

    # Which declared lever each failure maps to, and whether it aligned -- the
    # "fails legibly" check. A histogram of failure classes over the attempts.
    from collections import Counter
    fc_hist = Counter(
        r.get("failure_class") for r in run_records
        if not r.get("passed") and r.get("failure_class"))

    metrics = {
        "n": n,
        "c": c,
        "pass@1": est["p_hat"],   # kept for back-compat with existing readers
        "p_hat": est["p_hat"],
        "ci95": est["ci95"],
        "pass@k": est["pass@k"],
        "pass^k": est["pass^k"],
        "failure_breakdown": dict(fc_hist.most_common()),
    }

    from datetime import datetime, timezone
    summary = {
        "task": task_name,
        "model": model,
        "agent": "claude-code",
        "seed": run_records[0].get("seed") if run_records else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "attempts": [
            {
                # Physical run_N slot (matches report.json/ctrf); i+1 only as a
                # fallback when the run wasn't recorded with one.
                "attempt": r.get("attempt") or (i + 1),
                "passed": bool(r.get("passed")),
                "reward": r.get("reward"),
                "completion_rate": r.get("completion_rate"),
                "misbehaving_rate": r.get("misbehaving_rate"),
                "failure_class": r.get("failure_class"),
            }
            for i, r in enumerate(run_records)
        ],
    }
    if controls is not None:
        # {oracle_reward, nop_reward}. A task is admissible only if the oracle
        # scores 1.0 and nop scores 0.0; otherwise a 0/k is an author bug, not
        # difficulty, and reporting a tier would poison the corpus.
        summary["controls"] = controls
        summary["admissible"] = (
            controls.get("oracle_reward") == 1.0
            and (controls.get("nop_reward") or 0.0) == 0.0
        )
    (trials_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))

    pairs_lines = []
    for i, r in enumerate(run_records):
        pairs_lines.append(json.dumps({
            "task": task_name,
            "seed": r.get("seed"),
            "attempt": r.get("attempt") or (i + 1),
            "instruction": instruction or r.get("query", ""),
            "response": r.get("final_message", ""),
        }, ensure_ascii=False))
    (trials_dir / "pairs.jsonl").write_text("\n".join(pairs_lines) + "\n"
                                            if pairs_lines else "")

    failures = [
        {
            "attempt": r.get("attempt") or (i + 1),
            "failure_class": r.get("failure_class"),
            "reason": r.get("reason"),
        }
        for i, r in enumerate(run_records)
        if not r.get("passed")
    ]
    (trials_dir / "failure_analysis.json").write_text(
        json.dumps(failures, indent=2, ensure_ascii=False))

    return trials_dir
