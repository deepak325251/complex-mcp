"""Derive a task's ground truth from its oracle.

ComplexMCP hand-annotated 47 tasks and called it labour-intensive. This is the
step that turns ground truth from an authored artifact into a generated one:
run the oracle, diff the world before against the world after, and write the
four files the verifier needs.

    initial_state.json    the world at t=0
    expected_state.json   the world the oracle produced
    judge_spec.json       every leaf the oracle changed (positive) + a sample
                          it left alone (negative)
    gold_plan.json        the oracle's call sequence, as a dependency chain

An authored spec is a *design document* -- valuable for review, but it cannot
be the grading surface. Two failure modes make that unsafe, and both were live
in the three tasks this was written for:

  * a key the author believed exists but the dump does not contain (wrong
    prefix, wrong nesting) silently never matches, and
  * a spec whose schema does not parse leaves `total == 0`, which makes
    `completion_rate` vacuously 1.0 -- every run passes, including nop.

Deriving removes the guess. The author's spec stays on disk as the review
artifact; `compare_authored()` diffs the two so an intent the deriver missed is
visible instead of silently dropped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .facade.trace import load_trace
from .verify.graph import flatten_trace
from .verify.judge import JudgeSpec, derive_spec, judge

DERIVED = ("initial_state.json", "expected_state.json",
           "judge_spec.json", "gold_plan.json")


def _load(p: Path, default: Any = None) -> Any:
    if not p.is_file():
        return default
    text = p.read_text().strip()
    return json.loads(text) if text else default


def build_gold_plan(trace: list[dict]) -> list[list[dict]]:
    """Oracle trace -> the dependency chain `graph.evaluate` scores against.

    A linear chain: step i depends on step i-1. That understates the true DAG --
    reading the forecast and reading the cart are genuinely independent -- but
    the graph scorer uses dependencies only to fix *relative order*, and the
    oracle's own order is the one order known to work. Inferring a looser DAG
    would let a plan score full marks for an ordering the environment's gates
    would actually reject.
    """
    plan: list[list[dict]] = []
    for i, (server, tool) in enumerate(flatten_trace(trace)):
        plan.append([{
            "server_name": server,
            "tool_name": tool,
            "dependencies": [i - 1] if i else [],
        }])
    return plan


def _outcome(task: Path) -> str:
    import tomllib

    f = task / "task.toml"
    if not f.is_file():
        return "completion"
    md = tomllib.loads(f.read_text()).get("metadata", {})
    return str(md.get("outcome", "completion")).strip().lower()


def derive(task: Path, oracle_dir: Path, *, negative_sample: int = 400,
           write: bool = True) -> dict:
    """Write the four ground-truth files into `task/tests/` from an oracle run."""
    initial = _load(oracle_dir / "initial_state.json")
    final = _load(oracle_dir / "final_state.json")
    trace = load_trace(oracle_dir / "trace.jsonl")

    missing = [n for n, v in (("initial_state.json", initial),
                              ("final_state.json", final)) if not v]
    if missing:
        raise FileNotFoundError(
            f"oracle run at {oracle_dir} produced no {', '.join(missing)}. "
            f"Declare it under [artifacts] in task.toml and re-run the oracle.")

    spec = derive_spec(initial, final, negative_sample=negative_sample)
    plan = build_gold_plan(trace)

    # A refusal oracle correctly changes NOTHING, so it derives no positive
    # keys by design -- the grading surface is authored checks plus the rubric,
    # not a state diff. Applying the completion-semantics guard here rejected a
    # perfectly good refusal task for behaving exactly as intended.
    refusal = _outcome(task) == "refusal"
    if refusal and spec.positive:
        raise AssertionError(
            f"refusal oracle CHANGED state ({len(spec.positive)} key(s)): a correct "
            f"refusal leaves the world untouched, so this oracle is not a reference "
            f"answer. First changed: {spec.positive[0].path}")

    # A spec with no positive keys makes completion_rate vacuously 1.0 --
    # every run passes, including nop. That is the exact failure this module
    # exists to prevent, so it must never be written to disk.
    if not refusal and not spec.positive:
        raise AssertionError(
            f"derived 0 positive keys from {len(trace)} oracle call(s): the oracle "
            f"changed no state. Either it failed to run (check solve.sh exists and "
            f"the trial log) or the task writes nothing.")

    # An oracle that swallowed a failed call produces a PARTIAL world, and
    # deriving from it bakes the omission into expected_state -- so every model
    # that does the step correctly is then graded wrong. That is the most
    # damaging failure this harness can have: it does not merely lose a signal,
    # it inverts one, and the exported pairs teach the mistake.
    #
    # It happened: complexmcp-l4-s42's add_passenger and add_to_booking both
    # failed validation, the oracle exited 0 anyway, and five correct runs were
    # scored as failures.
    bad = [r for r in trace if r.get("status") in ("error", "malformed")]
    if bad:
        lines = "\n".join(
            f"    {r.get('i')}. {r.get('tool')} -> {str(r.get('response'))[:120]}"
            for r in bad[:8])
        raise AssertionError(
            f"oracle made {len(bad)} failed call(s); its final state is a partial "
            f"solution and must not become ground truth:\n{lines}")

    # The oracle must score 1.0 against its own spec. If it does not, the
    # deriver has a bug -- fail here rather than shipping a task whose ceiling
    # is unreachable.
    self_check = judge(initial, final, final, spec)
    if not refusal and not self_check.passed:
        raise AssertionError(
            f"derived spec does not validate against the oracle that produced it: "
            f"Rc={self_check.completion_rate:.3f} Rb={self_check.misbehaving_rate:.3f}. "
            f"This is a deriver bug, not a task bug.")

    out = {
        "initial_state.json": initial,
        "expected_state.json": final,
        "judge_spec.json": spec.to_dict(),
        "gold_plan.json": plan,
    }
    if write:
        tests = task / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        for name, payload in out.items():
            (tests / name).write_text(json.dumps(payload, indent=2))

    return {
        "positive": len(spec.positive),
        "negative": len(spec.negative),
        "plan_nodes": len(plan),
        "servers": sorted(initial) if isinstance(initial, dict) else [],
        "trace_calls": len(trace),
    }


# --------------------------------------------------------------------------
# authored spec -> derived spec reconciliation
# --------------------------------------------------------------------------

def compare_authored(authored: dict, derived_spec: JudgeSpec) -> dict:
    """Report which authored intents the derived spec covers.

    The authored file uses a different vocabulary on purpose -- it is written by
    a human describing goals ("portfolio empty, account flat"), not by a differ
    enumerating leaves. So this matches on path PREFIX, not equality: an authored
    `LightStock.portfolio` is considered covered if any derived key-path passes
    through those segments.

    Anything uncovered is not automatically a bug. It is either an intent the
    oracle never exercised (the task is under-specified) or a path the author
    wrote against the wrong dump shape (the design doc is stale). Both are worth
    a human look; neither should be silently dropped.
    """
    def norm(p: Any) -> tuple[str, ...]:
        if isinstance(p, str):
            return tuple(s for s in p.replace("[", ".").replace("]", "").split(".") if s)
        return tuple(str(s) for s in p)

    derived = [tuple(str(s) for s in k.path) for k in derived_spec.positive]
    dneg = [tuple(str(s) for s in k.path) for k in derived_spec.negative]

    def covered(want: tuple[str, ...], have: list[tuple[str, ...]]) -> bool:
        # Drop the server envelope ("output"/"status") the dump adds, so an
        # authored LightShop.cart still matches a derived LightShop.output.cart.
        want = tuple(s for s in want if not s.startswith("<"))
        return any(all(s in path for s in want) for path in have)

    pos = authored.get("positive_keys", authored.get("positive", []))
    neg = authored.get("negative_keys", authored.get("negative", []))

    return {
        "authored_positive": len(pos),
        "authored_negative": len(neg),
        "uncovered_positive": [
            k.get("path") for k in pos if not covered(norm(k.get("path", "")), derived)],
        "uncovered_negative": [
            k.get("path") for k in neg if not covered(norm(k.get("path", "")), dneg)],
    }
