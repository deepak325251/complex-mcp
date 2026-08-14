"""Task authoring gate — catch the grading defects that shipped by hand.

Three checks, each targeting a defect class we had to fix after the fact:

  gold_plan   every gold_plan tool_name is a REAL tool the app publishes
              (catches graph_f1 graded in a fictional namespace / fuzzy aliasing)
  ground_truth  gt_env matches the SEEDED world (entities exist; not baked
              against a different seed / hand-fabricated ids)
  traj_tests  every test_weights.json traj key maps to a real test function
              (a name typo silently scores the traj channel 0)

Importable (`validate(task_dir) -> report`) and a CLI that exits non-zero on any
hard problem, so it can gate authoring / CI. Purely additive — reads task files,
mutates nothing.

    python -m benchmark.validate_task bundle/input/02-auth-v2-rollout-coordination
    python -m benchmark.validate_task --all bundle/input
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_TOOL_RE = re.compile(r"^\s*async def ([a-z][a-z0-9_]*)\s*\(", re.MULTILINE)
_SKIP_TOOLS = {"login", "logout"}


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def registered_tools(app):
    """Tool names an app actually publishes (async defs in software/<App>/app.py),
    minus the login/logout plumbing. Empty set if the app can't be found."""
    path = os.path.join(_ROOT, "software", app, "app.py")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        names = set(_TOOL_RE.findall(f.read()))
    return names - _SKIP_TOOLS


def check_gold_plan(task_dir):
    problems = []
    gp = _load_json(os.path.join(task_dir, "tests", "gold_plan.json"))
    if gp is None:
        return ["gold_plan.json missing or invalid"]
    for i, node in enumerate(gp):
        for call in (node if isinstance(node, list) else [node]):
            server = call.get("server_name")
            tool = call.get("tool_name")
            if not server or not tool:
                continue
            pub = registered_tools(server)
            if not pub:
                problems.append(f"node {i}: app {server!r} not found under software/")
            elif tool not in pub:
                problems.append(
                    f"node {i}: {server}.{tool} is not a published tool "
                    f"(fictional namespace) — real tools: {sorted(pub)[:6]}…")
    return problems


def _all_light_apps():
    base = os.path.join(_ROOT, "software")
    return {d for d in os.listdir(base) if d.startswith("Light")} \
        if os.path.isdir(base) else set()


def _app_tool(name, apps):
    """Split 'App::tool' / 'App.tool' / 'App_tool' -> (app, tool)."""
    for sep in ("::", "."):
        if sep in name:
            a, t = name.split(sep, 1)
            return a, t
    if "_" in name:
        for a in apps:
            if name.startswith(a + "_"):
                return a, name[len(a) + 1:]
    return None, name


def _efs_names(efs):
    """Every tool name referenced by an efs.json, across BOTH shapes: the
    registry list-of-lists and the {step, alternatives} dict form."""
    names = []
    for s in (efs or {}).get("sets", []) or []:
        if isinstance(s, dict):
            if s.get("step"):
                names.append(s["step"])
            names += list(s.get("alternatives", []) or [])
        elif isinstance(s, list):
            names += [x for x in s if isinstance(x, str)]
    return names


def check_gold_sources(task_dir):
    """graph_f1 draws its gold from solution/trajectory.json (load_gold prefers
    it) and expands names via efs.json. Both must reference REAL tools, else a
    fictional name sneaks a match through EFS aliasing even when gold_plan.json
    is clean."""
    problems = []
    apps = _all_light_apps()
    sol = _load_json(os.path.join(task_dir, "solution", "trajectory.json"))
    if sol is not None:
        steps = sol.get("steps") if isinstance(sol, dict) else sol
        for s in steps or []:
            tool = s.get("tool") if isinstance(s, dict) else None
            if not tool:
                continue
            a, t = _app_tool(tool, apps)
            if a and t and t not in registered_tools(a):
                problems.append(f"solution/trajectory.json: {tool} is not a "
                                f"published tool (load_gold uses this source)")
    efs = _load_json(os.path.join(task_dir, "tests", "efs.json"))
    if efs is not None:
        for name in _efs_names(efs):
            a, t = _app_tool(name, apps)
            if a and t and t not in registered_tools(a):
                problems.append(f"efs.json: {name} is not a published tool "
                                f"(EFS alias to a fictional tool -> fuzzy match)")
    return problems


def check_ground_truth(task_dir):
    """gt_env must describe the SEEDED world. If an oracle exists we boot the
    world in-process and check the checked-in gt_env is admissible against it
    (entities present, same world instance)."""
    problems = []
    gt = _load_json(os.path.join(task_dir, "tests", "gt_env.json"))
    if gt is None:
        return ["gt_env.json missing or invalid"]
    oracle = _load_json(os.path.join(task_dir, "tests", "oracle.json"))
    if oracle is None:
        return ["oracle.json missing — cannot derive/validate GT in-process "
                "(hand-authored GT is unverifiable)"]
    try:
        from benchmark.bake_state_mcp import bake
        old, _fresh_gt = bake(task_dir, write=False)   # dry run: boot + oracle
    except SystemExit as exc:
        return [f"world/oracle does not bake: {exc}"]
    from benchmark.weighted_judge import state_admissibility, _world_mismatch
    ok, reason = state_admissibility(old, gt, gt)
    if not ok:
        problems.append(f"gt_env inadmissible against the seeded world: {reason} "
                        f"(GT baked for a different world/seed, or hand-fabricated)")
    elif _world_mismatch(old, gt):
        problems.append("gt_env entity ids are disjoint from the seeded world")
    return problems


def _test_functions(task_dir):
    path = os.path.join(task_dir, "tests", "test_outputs.py")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    return {n.name for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test")}


def check_traj_tests(task_dir):
    problems = []
    tw = _load_json(os.path.join(task_dir, "tests", "test_weights.json"))
    if tw is None:
        return []                                       # traj channel optional
    spec = (tw.get("components", {}) or {}).get("traj_tests", {})
    tests_map = spec.get("tests") if isinstance(spec, dict) else None
    if not tests_map:
        return []
    funcs = _test_functions(task_dir)
    if funcs is None:
        return ["test_weights names traj tests but test_outputs.py is missing"]
    for key in tests_map:
        base = key.split("[", 1)[0]                     # strip pytest params
        if base not in funcs:
            problems.append(
                f"traj test key {key!r} has no matching function in "
                f"test_outputs.py (would silently score 0)")
    return problems


_CHECKS = {
    "gold_plan": check_gold_plan,
    "gold_sources": check_gold_sources,
    "ground_truth": check_ground_truth,
    "traj_tests": check_traj_tests,
}

# NOTE: the seed pipeline's two authoring lints (bundle_complete, rubric_trace)
# are deliberately NOT registered here. They enforce the pipeline-emitted
# superset schema (tests/oracle.json + gt_env + rubric + …), which the 43
# harbor_final_all state-diff bundles legitimately do not carry. Registering
# them globally would fail every legacy bundle. seed/finish.py runs them
# alongside validate() for pipeline bundles instead. See seed/BUNDLE_SCHEMA.md.


def validate(task_dir):
    """Return {ok, checks: {name: [problems]}, problems: [all]}."""
    checks, allp = {}, []
    for name, fn in _CHECKS.items():
        try:
            probs = fn(task_dir)
        except Exception as exc:                        # a check must not crash the gate
            probs = [f"{name} check errored: {type(exc).__name__}: {exc}"]
        checks[name] = probs
        allp.extend(probs)
    return {"ok": not allp, "task": os.path.basename(task_dir.rstrip("/")),
            "checks": checks, "problems": allp}


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit("usage: python -m benchmark.validate_task <task_dir> "
                         "| --all <parent_dir>")
    if args[0] == "--all":
        parent = args[1]
        dirs = [os.path.join(parent, d) for d in sorted(os.listdir(parent))
                if os.path.isdir(os.path.join(parent, d, "tests"))]
    else:
        dirs = args
    bad = 0
    for d in dirs:
        rep = validate(d)
        mark = "PASS" if rep["ok"] else "FAIL"
        print(f"[{mark}] {rep['task']}")
        for p in rep["problems"]:
            print(f"   - {p}")
        bad += 0 if rep["ok"] else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
