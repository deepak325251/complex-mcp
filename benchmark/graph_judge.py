"""ETOM-style plan grading — WORLD-INDEPENDENT.

Scores the agent's tool-call sequence against the task's gold tool-DAG
(gold_plan.json), with equal-function-sets, using dependency-aware
precision/recall/F1. It never touches world state OR world-specific values
(uids, tickers, IDs) -- only "did the agent call the right tools in the right
dependency order", exactly like ETOM's GraphEvaluator. This removes the entire
seeded-world / frozen-fixture mismatch: there is nothing about the world to get
wrong.

  reward = 1.0 iff graph_f1 >= threshold  (default 1.0 = exact plan match, with
           equivalence sets so a valid alternative tool is not punished).

An optional rubric (Channel B) can still judge the deliverable text; it is not
required and does not reintroduce world-state dependence.
"""

from __future__ import annotations

import json
import os
import re

from benchmark.graph import evaluate

_SERVER_PREFIX = re.compile(r"^Light[A-Za-z0-9]+_")


def _bare(name: str | None) -> str:
    if not name:
        return ""
    return _SERVER_PREFIX.sub("", name.split("::")[-1])


def _efs_name_map(efs: dict | None) -> dict[str, set[str]]:
    """bare tool name -> set of equivalent bare names (from efs.json sets)."""
    out: dict[str, set[str]] = {}
    for s in (efs or {}).get("sets", []) or []:
        bare = {t.split("::")[-1] for t in s}
        for n in bare:
            out.setdefault(n, set()).update(bare)
    return out


def load_efs(task_dir: str | None) -> dict | None:
    """Prefer the task's tests/efs.json, else the global registry/efs.json."""
    for p in ([os.path.join(str(task_dir), "tests", "efs.json")] if task_dir else []) + \
             ["registry/efs.json"]:
        if os.path.exists(p):
            try:
                return json.load(open(p))
            except (OSError, json.JSONDecodeError):
                continue
    return None


def load_gold(task_dir: str) -> list | None:
    """The gold tool-DAG, world-independent.

    Prefer the ORACLE's own tool sequence (solution/trajectory.json) -- its tool
    names are correct by construction. Fall back to tests/gold_plan.json (which
    may carry stale names). Oracle steps are treated as an unordered set (deps
    empty): the grade is "did the agent call the right tools (with equivalence
    sets), not a pile of wrong ones" -- ETOM's tool-set + EFS signal.
    """
    op = os.path.join(str(task_dir), "solution", "trajectory.json")
    if os.path.exists(op):
        try:
            plan = json.load(open(op))
        except (OSError, json.JSONDecodeError):
            plan = None
        # Accept both shapes: a list of {tool,args} OR {"steps":[{tool,...}]}.
        steps = plan.get("steps") if isinstance(plan, dict) else plan
        if isinstance(steps, list) and steps:
            return [[{"server_name": "", "tool_name": _bare(s.get("tool")),
                      "dependencies": []}]
                    for s in steps if isinstance(s, dict) and s.get("tool")]
    gp = os.path.join(str(task_dir), "tests", "gold_plan.json")
    if os.path.exists(gp):
        try:
            return json.load(open(gp))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def judge_trajectory_graph(trajectory: dict, gold_plan: list, *,
                           efs: dict | None = None,
                           threshold: float = 1.0,
                           final_message: str | None = None,
                           rubric_judge=None, rubric_path: str | None = None) -> dict:
    # Accept both shapes: the live {"steps":[...]} dict AND the on-disk oracle
    # format, which is a top-level list of {tool,args,...}. Reading only `steps`
    # off a dict would silently score a raw-list trajectory as an empty plan.
    if isinstance(trajectory, dict):
        steps = trajectory.get("steps", [])
    elif isinstance(trajectory, list):
        steps = trajectory
    else:
        steps = []
    # Predicted plan: bare tool names, server-agnostic (world-independent).
    predicted = [("", _bare(s.get("tool"))) for s in steps
                 if isinstance(s, dict) and s.get("tool")]

    namemap = _efs_name_map(efs)
    gold: list[list[dict]] = []
    for step in gold_plan or []:
        alts = step if isinstance(step, list) else [step]
        names: set[str] = set()
        deps: set[int] = set()
        for a in alts:
            tn = a.get("tool_name") or a.get("tool")
            if tn:
                names.add(tn)
                names.update(namemap.get(tn, set()))   # equal-function-set expansion
            for d in (a.get("dependencies", []) or []):
                deps.add(d)
        gold.append([{"server_name": "", "tool_name": n, "dependencies": sorted(deps)}
                     for n in names])

    r = evaluate(gold, predicted)
    plan_ok = r.f1 >= threshold

    rubric_score = None
    rubric_per = None
    if rubric_judge is not None and rubric_path and os.path.exists(rubric_path):
        rub = json.load(open(rubric_path, encoding="utf-8"))
        criteria = rub.get("criteria", rub) if isinstance(rub, dict) else rub
        verdicts = rubric_judge(criteria, final_message or "")
        pos_total = sum(c["score"] for c in criteria if c["score"] > 0)
        met = pen = 0.0
        rubric_per = []
        for c in criteria:
            v = verdicts.get(c.get("number"))
            rubric_per.append({"number": c.get("number"), "criterion": c.get("criterion"),
                               "score": c.get("score"), "satisfied": bool(v)})
            if v:
                (met := met + c["score"]) if c["score"] > 0 else (pen := pen + abs(c["score"]))
        rubric_score = round(max(0.0, (met - pen) / pos_total), 4) if pos_total else None

    passed = plan_ok and (rubric_score is None or rubric_score >= 0.5)
    return {
        # Continuous reward = graph tool-DAG F1 (partial credit). `passed`
        # stays the binary exact-match+rubric gate used for accuracy/pass@k.
        "reward": round(r.f1, 6),
        "passed": bool(passed),
        "graph_f1": round(r.f1, 6),
        "graph_precision": round(r.precision, 6),
        "graph_recall": round(r.recall, 6),
        # Map onto the completion/misbehave vocabulary the aggregates expect.
        "recall": r.tp, "total": r.total_gt_nodes, "misbehave": r.fp,
        "matched_nodes": r.matched_nodes, "missing_nodes": r.missing_nodes,
        "misplaced": r.misplaced,
        "rubric_score": rubric_score, "rubric_per_criterion": rubric_per,
        "grader": "graph_f1+efs(plan)",
    }
