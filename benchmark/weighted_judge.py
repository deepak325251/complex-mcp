"""Weighted grading: combine state-diff, plan-shape, and rubric as weighted components.

Instead of picking ONE judge (state-diff `Rc/Rb` OR graph `F1`), this scores a run
as a weighted ledger where each signal is a *component* with a weight:

    reward = max(0, ( Σ  w_i · value_i     over positive components
                     − Σ |p_j| · severity_j over penalty  components ) / Σ positive_w)

A component's `value`/`severity` is a fraction in [0, 1], so a binary pytest test is
just the special case value ∈ {0, 1}. State-diff plugs in graded:
    state_completion  value    = Rc = recall / total          (positive)
    state_misbehave   severity = Rb = misbehave / total       (penalty)
    graph_plan        value    = graph_f1                     (positive)
    rubric            value    = Channel-B score              (positive, optional)

Degradation (seedless reality): if the ground-truth world (`gt_env`) is missing or
stale, the two `state_*` components drop out and `Σ positive_w` renormalizes around
what remains — the score stays valid, just plan/rubric-driven, and is marked
`state: "unavailable"` rather than silently scored zero.

The result dict carries `recall`/`total`/`misbehave` so the existing completion &
misbehave-rate aggregates in run_benchmark keep working.
"""

from __future__ import annotations

import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Defaults — used when a task ships no tests/test_weights.json.
# ---------------------------------------------------------------------------
DEFAULT_THRESHOLD = 1.0
DEFAULT_WEIGHTS = {
    "state_completion": {"weight": 5, "graded": True},
    "state_misbehave": {"weight": -4, "graded": True},
    "graph_plan": {"weight": 3, "graded": True},
    "traj_tests": {"weight": 0, "graded": True},  # 0 = off unless a task opts in
    "rubric": {"weight": 0, "graded": True},       # 0 = off unless a task opts in
}

_SERVER_PREFIX = re.compile(r"^Light[A-Za-z0-9]+_")


# ---------------------------------------------------------------------------
# State-diff — vendored verbatim from tests/verify.py so this module is
# self-contained and grades without a ComplexMCP install.
# ---------------------------------------------------------------------------
def lev_sim(x, y):
    if x is None or y is None:
        return 0.0
    if x == y:
        return 1.0
    la, lb = len(x), len(y)
    if la == 0 or lb == 0:
        return 0.0
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if x[i - 1] == y[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return 1.0 - prev[lb] / max(la, lb)


def exact_match(x, y):
    return x == y


def fuzzy_match(x, y):
    if x is None:
        return y is None
    if y is None:
        return x is None
    x = x.lower().strip()
    y = y.lower().strip()
    return y == x or (len(x) >= 10 and y in x) or lev_sim(x, y) > 0.7


exclude_keys = {
    "timestamp",
    "mid", "moid", "cid", "gid",   # LightTalk
    "sid", "tid", "caid", "trid",  # LightShop (trid = random per-checkout txn id)
    "aid",                         # LightWeather
    "bid", "brid", "rid",          # LightFlight
    "oid",                         # LightStock
    "nid",                         # LightNews
}

eq_methods = {"content": fuzzy_match}


def _at(arr, idx):
    if not isinstance(arr, list):
        return None
    return arr[idx] if idx < len(arr) else None


def _get(dic, key):
    if not isinstance(dic, dict):
        return None
    return dic.get(key)


def judge_env(old_env, new_env, gt_env):
    """Recursive state diff → {total, recall, misbehave}. See verify.py."""
    total = recall = misbehave = 0

    def dfs(old_item, new_item, gt_item, key=""):
        nonlocal total, recall, misbehave
        if key in exclude_keys:
            return
        if isinstance(gt_item, list):
            length = max(
                len(gt_item),
                len(old_item) if isinstance(old_item, list) else 0,
                len(new_item) if isinstance(new_item, list) else 0,
            )
            for i in range(length):
                dfs(_at(old_item, i), _at(new_item, i), _at(gt_item, i), key=key)
            return
        if isinstance(gt_item, dict):
            keys = set(
                list(gt_item.keys())
                + (list(old_item.keys()) if isinstance(old_item, dict) else [])
                + (list(new_item.keys()) if isinstance(new_item, dict) else [])
            )
            for sub_key in keys:
                dfs(_get(old_item, sub_key), _get(new_item, sub_key),
                    _get(gt_item, sub_key), key=sub_key)
            return
        eq = eq_methods.get(key, exact_match)
        if eq(old_item, gt_item):
            if not eq(old_item, new_item):
                misbehave += 1
        else:
            total += 1
            if eq(new_item, gt_item):
                recall += 1

    dfs(old_env, new_env, gt_env)
    return {"total": total, "recall": recall, "misbehave": misbehave}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def _normalize_traj(trajectory):
    """Accept the on-disk oracle shape (a top-level list of {tool,args,...}) as
    well as the live shape {"steps": [...]}. The graph judge only reads `steps`
    off a dict, so a raw list would otherwise score as an empty plan."""
    if isinstance(trajectory, list):
        return {"steps": trajectory, "final_message": ""}
    if isinstance(trajectory, dict):
        return trajectory
    return {"steps": []}


def load_weights(grading_dir=None):
    """Load tests/test_weights.json, merged over DEFAULT_WEIGHTS.

    Accepts either the flat legacy shape {name: weight} or the component shape
    {"threshold": .., "components": {name: {"weight": .., "graded": ..}}}.
    Unknown/plain numeric entries are treated as graded positive components.
    """
    threshold = DEFAULT_THRESHOLD
    components = {k: dict(v) for k, v in DEFAULT_WEIGHTS.items()}

    path = os.path.join(str(grading_dir), "test_weights.json") if grading_dir else None
    if path and os.path.exists(path):
        try:
            raw = json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            threshold = raw.get("threshold", threshold)
            # A flat {name: weight} file is the *pytest* weights schema
            # (consumed by pytest_judge). Only an explicit "components" block
            # feeds this component grader — otherwise bare pytest test names
            # would become zero-value components and wrongly drag the score down.
            comp = raw.get("components")
            for name, spec in (comp.items() if isinstance(comp, dict) else []):
                if isinstance(spec, (int, float)):
                    components[name] = {"weight": spec, "graded": True}
                elif isinstance(spec, dict):
                    components.setdefault(name, {})
                    components[name].update(spec)
                    components[name].setdefault("graded", True)
    return threshold, components


# ---------------------------------------------------------------------------
# Rubric (Channel B) — optional
# ---------------------------------------------------------------------------
def _run_traj_pytest(test_file, trajectory):
    """Run a task's test_outputs.py against the agent trajectory (world-free) and
    return {test_name: passed}. The trajectory is staged at $COMPLEXMCP_TRAJECTORY,
    which is what benchmark.traj_asserts reads."""
    import pytest
    import tempfile

    passed = {}

    class _Collector:
        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                passed[report.nodeid.split("::")[-1]] = report.passed

    with tempfile.TemporaryDirectory() as tmp:
        tpath = os.path.join(tmp, "trajectory.json")
        with open(tpath, "w") as fh:
            json.dump(trajectory or {"steps": []}, fh)
        prev = os.environ.get("COMPLEXMCP_TRAJECTORY")
        os.environ["COMPLEXMCP_TRAJECTORY"] = tpath
        try:
            from benchmark import traj_asserts
            traj_asserts._CACHE.clear()
        except Exception:
            pass
        try:
            pytest.main([test_file, "-q", "-p", "no:cacheprovider",
                         "--import-mode=importlib"], plugins=[_Collector()])
        finally:
            if prev is None:
                os.environ.pop("COMPLEXMCP_TRAJECTORY", None)
            else:
                os.environ["COMPLEXMCP_TRAJECTORY"] = prev
    return passed


def _score_traj_tests(passed, tests_map):
    """Weighted pytest score in [0, 1]: positive tests earn, guard tests (negative
    weight) that fire subtract. Guards are netted inside the component value, so a
    tripped guardrail lowers the reward without a separate ledger row.

    tests_map may be {name: weight}. Missing -> convention: a name containing
    'guard' is a negative guard (-1), everything else is positive (+1)."""
    if not tests_map:
        tests_map = {n: (-1 if "guard" in n else 1) for n in passed}
    pos_total = sum(w for w in tests_map.values() if w > 0)
    earned = penalty = 0.0
    recall = total = misbehave = 0
    for name, w in tests_map.items():
        if w > 0:
            total += 1
        if not passed.get(name, False):
            continue
        if w > 0:
            earned += w
            recall += 1
        else:
            penalty += abs(w)
            misbehave += 1
    value = max(0.0, (earned - penalty) / pos_total) if pos_total else 0.0
    return value, {"recall": recall, "total": total, "misbehave": misbehave}


def _score_rubric(criteria, verdicts):
    """Weighted rubric score in [0, 1] from {criterion_number: bool} verdicts."""
    met = pen = pos_total = 0.0
    per = []
    for c in criteria or []:
        w = c.get("score", 0) or 0
        if w > 0:
            pos_total += w
        v = bool(verdicts.get(c.get("number")))
        per.append({"number": c.get("number"), "criterion": c.get("criterion"),
                    "score": w, "satisfied": v})
        if v:
            if w > 0:
                met += w
            else:
                pen += abs(w)
    score = round(max(0.0, (met - pen) / pos_total), 4) if pos_total else None
    return score, per


# ---------------------------------------------------------------------------
# The combined judge
# ---------------------------------------------------------------------------
def judge_weighted(
    *,
    old_env=None,
    new_env=None,
    gt_env=None,
    trajectory=None,
    gold_plan=None,
    efs=None,
    grading_dir=None,
    weights=None,
    threshold=None,
    final_message=None,
    rubric_judge=None,
    rubric_path=None,
    plan_threshold=1.0,
):
    """Score a run as a weighted ledger of components. Returns a dict shaped to
    drop into run_benchmark.py (`reward`/`passed`/`recall`/`total`/`misbehave`)."""
    if weights is None or threshold is None:
        _thr, _weights = load_weights(grading_dir)
        weights = weights or _weights
        threshold = threshold if threshold is not None else _thr

    trajectory = _normalize_traj(trajectory)
    components: dict[str, dict] = {}   # name -> {weight, value|severity, ...}
    state_available = (
        old_env is not None and new_env is not None and gt_env is not None
    )

    # --- state components -----------------------------------------------------
    Rc = Rb = None
    state = None
    wants_state = _weight_of(weights, "state_completion") or _weight_of(weights, "state_misbehave")
    if state_available and wants_state:
        state = judge_env(old_env, new_env, gt_env)
        total = state["total"]
        Rc = (state["recall"] / total) if total else 1.0
        Rb = (state["misbehave"] / total) if total else float(state["misbehave"])
        Rb = min(Rb, 1.0)
        wc = _weight_of(weights, "state_completion")
        if wc:
            components["state_completion"] = {"weight": wc, "value": round(Rc, 4)}
        wm = _weight_of(weights, "state_misbehave")
        if wm:
            components["state_misbehave"] = {"weight": wm, "severity": round(Rb, 4)}

    # --- plan component -------------------------------------------------------
    graph = None
    wg = _weight_of(weights, "graph_plan")
    if wg and gold_plan is not None:
        from benchmark.graph_judge import judge_trajectory_graph
        graph = judge_trajectory_graph(
            trajectory or {"steps": []}, gold_plan, efs=efs,
            threshold=plan_threshold, final_message=None,
            rubric_judge=None, rubric_path=None)
        components["graph_plan"] = {"weight": wg, "value": graph["graph_f1"]}

    # --- trajectory pytest component (world-free guards + arg checks) --------
    traj = None
    wt = _weight_of(weights, "traj_tests")
    tt_spec = weights.get("traj_tests") if isinstance(weights.get("traj_tests"), dict) else {}
    if wt and grading_dir:
        test_file = os.path.join(str(grading_dir), tt_spec.get("test_file", "test_outputs.py"))
        if os.path.exists(test_file):
            passed = _run_traj_pytest(test_file, trajectory)
            val, traj = _score_traj_tests(passed, tt_spec.get("tests"))
            traj["passed_tests"] = passed
            components["traj_tests"] = {"weight": wt, "value": round(val, 4)}

    # --- rubric component (optional) -----------------------------------------
    rubric_score = None
    rubric_per = None
    wr = _weight_of(weights, "rubric")
    if wr and rubric_judge is not None and rubric_path and os.path.exists(rubric_path):
        try:
            _rub = json.load(open(rubric_path, encoding="utf-8"))
            # rubric.json is either {"criteria": [...]} or a bare list of criteria.
            criteria = _rub.get("criteria", []) if isinstance(_rub, dict) else _rub
        except (OSError, json.JSONDecodeError):
            criteria = []
        verdicts = rubric_judge(criteria, final_message or "") or {}
        rubric_score, rubric_per = _score_rubric(criteria, verdicts)
        if rubric_score is not None:
            components["rubric"] = {"weight": wr, "value": rubric_score}

    # --- reduce ---------------------------------------------------------------
    earned = penalty = pos_total = 0.0
    for name, c in components.items():
        w = c["weight"]
        if w > 0:
            pos_total += w
            c["earned"] = round(w * c.get("value", 0.0), 4)
            earned += c["earned"]
        else:
            # cap each penalty at its own weight so one signal can't over-punish.
            c["penalty"] = round(min(abs(w) * c.get("severity", 0.0), abs(w)), 4)
            penalty += c["penalty"]

    reward = round(max(0.0, (earned - penalty) / pos_total), 6) if pos_total else 0.0
    passed = bool(pos_total) and reward >= threshold

    # --- aggregate passthrough (state preferred, else plan) ------------------
    if state is not None:
        recall, total_n, misbehave = state["recall"], state["total"], state["misbehave"]
    elif traj is not None:
        recall, total_n, misbehave = traj["recall"], traj["total"], traj["misbehave"]
    elif graph is not None:
        recall, total_n = graph.get("tp", 0), graph.get("total_gt_nodes", 0)
        misbehave = graph.get("fp", 0)
    else:
        recall = total_n = misbehave = 0

    label = _label(Rc, Rb, graph, state_available, plan_threshold)

    return {
        "reward": reward,
        "passed": passed,
        "quadrant": label,
        "threshold": threshold,
        "components": components,
        "earned": round(earned, 4),
        "penalty": round(penalty, 4),
        "pos_total": pos_total,
        # aggregate vocabulary
        "recall": recall,
        "total": total_n,
        "misbehave": misbehave,
        # per-channel detail
        "state": (
            {"status": "unavailable"} if not state_available
            else {"Rc": round(Rc, 4), "Rb": round(Rb, 4), **state}
        ),
        "plan": None if graph is None else {
            "graph_f1": graph["graph_f1"],
            "graph_precision": graph["graph_precision"],
            "graph_recall": graph["graph_recall"],
            "missing_nodes": graph.get("missing_nodes"),
            "misplaced": graph.get("misplaced"),
        },
        "traj_tests": traj,
        "rubric_score": rubric_score,
        "rubric_per_criterion": rubric_per,
        "grader": "weighted(state+graph+rubric)",
    }


def _weight_of(weights, name):
    spec = weights.get(name) if isinstance(weights, dict) else None
    if isinstance(spec, dict):
        return spec.get("weight", 0) or 0
    if isinstance(spec, (int, float)):
        return spec
    return 0


def _label(Rc, Rb, graph, state_available, plan_threshold):
    if not state_available:
        return "PLAN_ONLY"
    state_ok = (Rc == 1.0 and Rb == 0.0)
    plan_ok = graph is not None and graph["graph_f1"] >= plan_threshold
    if graph is None:
        return "SOLVED" if state_ok else "FAILED"
    if state_ok and plan_ok:
        return "SOLVED"
    if state_ok and not plan_ok:
        return "BRUTE_FORCE"
    if plan_ok and not state_ok:
        return "EXECUTION_FAIL"
    return "FAILED"


# ---------------------------------------------------------------------------
# CLI — so tests/test.sh can invoke it in the verifier container.
#   OLD_ENV / NEW_ENV / GT_ENV        world snapshots  (state channel)
#   AGENT_TRAJECTORY / GOLD_PLAN      tool traces      (plan channel)
#   WEIGHTS                           test_weights.json (optional)
#   VERIFIER_LOG_DIR                  where reward.json is written
# ---------------------------------------------------------------------------
def _load(path):
    if path and os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.get
    old_env = _load(env("OLD_ENV", os.path.join(here, "old_env.json")))
    new_env = _load(env("NEW_ENV", os.path.join(here, "new_env.json")))
    gt_env = _load(env("GT_ENV", os.path.join(here, "gt_env.json")))
    trajectory = _load(env("AGENT_TRAJECTORY")) or {"steps": []}
    gold_plan = _load(env("GOLD_PLAN"))
    grading_dir = env("GRADING_DIR", here)
    efs = _load(env("EFS")) or _load(os.path.join(grading_dir, "efs.json")) \
        or _load("registry/efs.json")

    out = judge_weighted(
        old_env=old_env, new_env=new_env, gt_env=gt_env,
        trajectory=trajectory, gold_plan=gold_plan, efs=efs,
        grading_dir=grading_dir,
    )

    log_dir = env("VERIFIER_LOG_DIR", "/logs/verifier")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "reward.json"), "w") as f:
        json.dump(out, f, indent=2)
    with open(os.path.join(log_dir, "reward.txt"), "w") as f:
        # binary pass for harbor's scalar fallback
        f.write("1" if out["passed"] else "0")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
