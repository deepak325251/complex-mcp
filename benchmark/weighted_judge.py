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

Admissibility (the loud-failure rule): providing all three envs is NOT enough for
them to be *gradable*. A facade dump that came back empty (`output: {}`) or a
`gt_env` baked against a different seed/world would make the state-diff fabricate a
score (Rc≈0, or a false Rc=1.0 when there is nothing to grade) and report it as a
real state grade. `state_admissibility()` catches those up front, drops the state
components, and marks `state: {"status": "inadmissible", "reason": ...}` with the
exact defect — so a broken state channel can never masquerade as a low completion.

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
    # mcp-stump apps (Jira/Notion/Slack/…): generated ids and clock stamps are
    # non-deterministic across a GT bake and a live run, so grading them would
    # penalize a semantically-correct write. Grade content, not the receipt.
    "id", "ts",
    "created_time", "last_edited_time", "created", "updated_at",
    # Free-text write payloads (draft/message bodies, subjects, recipients) are
    # author-phrased and never reproduced verbatim by a free-form agent. Grading
    # them by exact string match makes any correct-but-differently-worded draft
    # score Rc=0. The STATE channel therefore verifies the structural fact (the
    # write happened, nothing protected changed); the CONTENT is enforced by the
    # traj-test content_contains fingerprints. Same "grade content, not the
    # receipt" rationale as the ids/stamps above.
    "to_addr", "cc_addr", "subject", "body",
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


# ---------------------------------------------------------------------------
# State-channel admissibility — refuse to *fake* a state grade when the inputs
# are broken. A missing dump, an empty facade dump, or a gt_env baked against a
# different world instance would otherwise make judge_env fabricate Rc≈0 (or a
# false Rc=1.0 when there is nothing to grade) and report it as a real score.
# We detect those and mark the channel inadmissible with a reason instead.
# ---------------------------------------------------------------------------
_CONTAINER_KEYS = {
    "pulls", "prs", "pages", "issues", "channels", "repos", "rooms",
    "tickets", "cards", "boards", "sprints", "users", "projects",
}


def _content(app_val):
    """Unwrap a facade dump entry ``{"status":..,"output":{...}}`` to its output;
    pass any other shape through unchanged."""
    if isinstance(app_val, dict) and "output" in app_val \
            and set(app_val) <= {"status", "output", "error"}:
        return app_val["output"]
    return app_val


def _is_empty(x):
    return x is None or x == {} or x == [] or x == ""


def _empty_dump_apps(new_env, gt_env):
    """Apps that gt_env expects to carry state but the served dump left empty —
    the Layer-1 broken-capture signature (``output: {}``)."""
    bad = []
    if not (isinstance(gt_env, dict) and isinstance(new_env, dict)):
        return bad
    for app, gtv in gt_env.items():
        if isinstance(app, str) and app.startswith("_"):
            continue
        if _is_empty(_content(gtv)):
            continue  # gt encodes nothing here → nothing to capture
        if _is_empty(_content(new_env.get(app))):
            bad.append(app)
    return bad


def _ids_by_container(node, parent_key="", acc=None):
    """Map each known collection container (pulls, pages, issues, channels, …)
    to the set of entity-id keys found under it. Grouping by container lets us
    spot a disjoint ``pulls`` set even when a parent ``repos`` id matches."""
    if acc is None:
        acc = {}
    if isinstance(node, dict):
        if parent_key in _CONTAINER_KEYS:
            acc.setdefault(parent_key, set()).update(
                k for k in node if isinstance(k, str))
        for k, v in node.items():
            _ids_by_container(v, k, acc)
    elif isinstance(node, list):
        for it in node:
            _ids_by_container(it, parent_key, acc)
    return acc


def _world_mismatch(new_env, gt_env):
    """True when, for some collection present in both, gt_env's entity ids and
    the served dump's ids are disjoint — gt_env was baked against a different
    seed/world (Layer 2). Per-container so a shared parent id can't mask it."""
    gt_ids = _ids_by_container(gt_env)
    new_ids = _ids_by_container(new_env)
    for container, gset in gt_ids.items():
        nset = new_ids.get(container)
        if gset and nset and gset.isdisjoint(nset):
            return True
    return False


def state_admissibility(old_env, new_env, gt_env):
    """Return ``(admissible: bool, reason: str)``. ``reason == "unavailable"``
    means the state channel simply wasn't provided (all envs None) — a normal
    plan-only task, not a defect. Any other reason is a real inadmissibility
    (broken capture or wrong-world ground truth)."""
    if old_env is None or new_env is None or gt_env is None:
        return False, "unavailable"
    empty = _empty_dump_apps(new_env, gt_env)
    if empty:
        return False, "empty_dump:" + ",".join(sorted(empty))
    if _world_mismatch(new_env, gt_env):
        return False, "world_mismatch"
    return True, None


def _state_report(admissible, reason, Rc, Rb, state):
    """Shape the per-run ``state`` field: 'unavailable' (no channel),
    'inadmissible' (channel broken, with reason), or the scored detail."""
    if reason == "unavailable":
        return {"status": "unavailable"}
    if not admissible:
        return {"status": "inadmissible", "reason": reason}
    rep = {"Rc": round(Rc, 4) if Rc is not None else None,
           "Rb": round(Rb, 4) if Rb is not None else None}
    if isinstance(state, dict):
        rep.update(state)
    return rep


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
def _run_traj_pytest(test_file, trajectory, envs=None):
    """Run a task's test_outputs.py and return {test_name: passed}.

    The trajectory is staged at $COMPLEXMCP_TRAJECTORY (read by traj_asserts) so
    world-FREE tests can check the agent's tool calls. When `envs` (old/new/gt
    snapshots) is given, they are ALSO staged at $COMPLEXMCP_{OLD,NEW,GT}_ENV so
    a world-FULL state-diff test case (via benchmark.state_asserts) runs in the
    SAME pytest suite — one uniform grader for tool checks + state diff + rubric."""
    import pytest
    import tempfile

    passed = {}

    class _Collector:
        def pytest_runtest_logreport(self, report):
            if report.when == "call":
                passed[report.nodeid.split("::")[-1]] = report.passed

    staged = {}   # env var -> temp file path we set (to restore afterwards)
    with tempfile.TemporaryDirectory() as tmp:
        def _stage(var, obj):
            path = os.path.join(tmp, var.lower() + ".json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(obj if obj is not None else {}, fh, ensure_ascii=False)
            staged[var] = os.environ.get(var)          # remember prior value
            os.environ[var] = path

        _stage("COMPLEXMCP_TRAJECTORY", trajectory or {"steps": []})
        if envs:
            _stage("COMPLEXMCP_OLD_ENV", envs.get("old_env"))
            _stage("COMPLEXMCP_NEW_ENV", envs.get("new_env"))
            _stage("COMPLEXMCP_GT_ENV", envs.get("gt_env"))
        for mod in ("traj_asserts", "state_asserts"):   # drop cross-run caches
            try:
                __import__("benchmark." + mod, fromlist=[mod])._CACHE.clear()
            except Exception:
                pass
        # Force a fresh import of the test module. A task that binds world state
        # at module load (e.g. INITIAL = S.old()) would otherwise reuse a STALE
        # module across pass@k attempts / episodes graded in this one process,
        # scoring every later run against the first run's world.
        _abs = os.path.abspath(test_file)
        for _name in [n for n, m in list(sys.modules.items())
                      if getattr(m, "__file__", None)
                      and os.path.abspath(m.__file__) == _abs]:
            sys.modules.pop(_name, None)
        try:
            pytest.main([test_file, "-q", "-p", "no:cacheprovider",
                         "--import-mode=importlib"], plugins=[_Collector()])
        finally:
            for var, prev in staged.items():
                if prev is None:
                    os.environ.pop(var, None)
                else:
                    os.environ[var] = prev
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
    """Weighted rubric score in [0, 1] from {criterion_number: bool} verdicts.

    Polarity: a criterion is a GUARD (violation-worded) when it is flagged
    ``is_positive: false`` OR carries a negative ``score``. For a guard,
    ``satisfied: true`` means the violation FIRED (a penalty) and
    ``satisfied: false`` means the run stayed clean (no credit, no penalty) — so
    a run that avoids every violation is never capped for it. Only positive
    criteria earn weight and define the denominator. This matches
    rubric_judge.evaluate_rubric; the old sign-only rule mis-scored guard
    criteria that authors wrote with a positive score + ``is_positive: false``
    (e.g. 5/19 instead of 5/10 on a clean run)."""
    met = pen = pos_total = 0.0
    per = []
    for c in criteria or []:
        w = c.get("score", 0) or 0
        is_pos = c.get("is_positive")
        # is_positive wins when present; else fall back to the sign of the score.
        guard = (is_pos is False) or (is_pos is None and w < 0)
        mag = abs(w)
        v = bool(verdicts.get(c.get("number")))
        per.append({"number": c.get("number"), "criterion": c.get("criterion"),
                    "score": w, "is_positive": (not guard), "satisfied": v})
        if guard:
            if v:
                pen += mag          # violation fired
        else:
            pos_total += mag
            if v:
                met += mag
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
    # Admissibility gate: providing the three envs is not enough — an empty dump
    # or a wrong-world gt_env must NOT be scored as if the agent did nothing.
    admissible, state_reason = state_admissibility(old_env, new_env, gt_env)
    state_available = admissible

    # --- state components -----------------------------------------------------
    Rc = Rb = None
    state = None
    wants_state = _weight_of(weights, "state_completion") or _weight_of(weights, "state_misbehave")
    if state_available and wants_state:
        state = judge_env(old_env, new_env, gt_env)
        total = state["total"]
        Rb = min((state["misbehave"] / total) if total else float(state["misbehave"]), 1.0)
        wm = _weight_of(weights, "state_misbehave")
        if wm:
            components["state_misbehave"] = {"weight": wm, "severity": round(Rb, 4)}
        # Completion is only gradable when the world encodes required changes.
        # total == 0 (a pure "don't touch anything" guardrail) must NOT earn a
        # false Rc = 1.0 — it simply leaves state_completion out of the ledger,
        # while state_misbehave above still guards against over-action.
        if total:
            Rc = state["recall"] / total
            wc = _weight_of(weights, "state_completion")
            if wc:
                components["state_completion"] = {"weight": wc, "value": round(Rc, 4)}

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
            # Hand the pytest suite the world snapshots too, so a state-diff test
            # case (benchmark.state_asserts) can run alongside the world-free
            # tool/answer checks in the same file.
            passed = _run_traj_pytest(test_file, trajectory, envs={
                "old_env": old_env, "new_env": new_env, "gt_env": gt_env})
            val, traj = _score_traj_tests(passed, tt_spec.get("tests"))
            traj["passed_tests"] = passed
            components["traj_tests"] = {"weight": wt, "value": round(val, 4)}

    # --- rubric component (optional) -----------------------------------------
    rubric_score = None
    rubric_per = None
    wr = _weight_of(weights, "rubric")
    # Run the judge whenever it's available and a rubric exists -- even at weight
    # 0 -- so rubric_score/rubric_per are populated for REPORTING. It is folded
    # into the reward ledger only when the task opts in with weight > 0.
    if rubric_judge is not None and rubric_path and os.path.exists(rubric_path):
        try:
            _rub = json.load(open(rubric_path, encoding="utf-8"))
            # rubric.json is either {"criteria": [...]} or a bare list of criteria.
            criteria = _rub.get("criteria", []) if isinstance(_rub, dict) else _rub
        except (OSError, json.JSONDecodeError):
            criteria = []
        verdicts = rubric_judge(criteria, final_message or "") or {}
        rubric_score, rubric_per = _score_rubric(criteria, verdicts)
        if wr and rubric_score is not None:
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
    # `misbehave_kind` records what the aggregate misbehave/total counts MEAN, so
    # downstream reporting can't relabel plan false-positives as state corruption.
    if state is not None:
        recall, total_n, misbehave = state["recall"], state["total"], state["misbehave"]
        misbehave_kind = "state_guard"
    elif traj is not None:
        recall, total_n, misbehave = traj["recall"], traj["total"], traj["misbehave"]
        misbehave_kind = "traj_guard"
    elif graph is not None:
        recall, total_n = graph.get("tp", 0), graph.get("total_gt_nodes", 0)
        misbehave = graph.get("fp", 0)
        misbehave_kind = "plan_fp"      # unmatched plan nodes, NOT state corruption
    else:
        recall = total_n = misbehave = 0
        misbehave_kind = None

    basis = sorted(components.keys())   # components that actually contributed
    label = _label(Rc, Rb, graph, state_available, wants_state, state_reason,
                   plan_threshold)

    return {
        "reward": reward,
        "passed": passed,
        "quadrant": label,
        "threshold": threshold,
        "components": components,
        "basis": basis,
        "earned": round(earned, 4),
        "penalty": round(penalty, 4),
        "pos_total": pos_total,
        # aggregate vocabulary
        "recall": recall,
        "total": total_n,
        "misbehave": misbehave,
        "misbehave_kind": misbehave_kind,
        # per-channel detail
        "state_admissible": admissible,
        "state_reason": state_reason,
        "state": _state_report(admissible, state_reason, Rc, Rb, state),
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
        # grader label names only the channels that actually contributed, so a
        # plan-only fallback can never be reported as "state+graph+rubric".
        "grader": "weighted(" + "+".join(basis) + ")" if basis else "weighted(empty)",
    }


def _weight_of(weights, name):
    spec = weights.get(name) if isinstance(weights, dict) else None
    if isinstance(spec, dict):
        return spec.get("weight", 0) or 0
    if isinstance(spec, (int, float)):
        return spec
    return 0


def _label(Rc, Rb, graph, state_available, wants_state, state_reason, plan_threshold):
    if not state_available:
        # Distinguish a task that simply has no state channel (PLAN_ONLY) from a
        # task whose state channel was provided but is broken (STATE_INADMISSIBLE).
        if wants_state and state_reason not in (None, "unavailable"):
            return "STATE_INADMISSIBLE"
        return "PLAN_ONLY"
    # Rc is None for a pure guardrail (no required changes) — then completion is
    # vacuously met and only the misbehave guard decides the state verdict.
    state_ok = (Rc is None or Rc == 1.0) and Rb == 0.0
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


def write_weighted_verifier(out_dir, result, grading_dir=None) -> str:
    """Write the FULL verifier/{reward.json, reward.txt, ctrf.json, detail.json}
    folder for a weighted grade — the same 4-file set the pytest+rubric grader
    (benchmark.pytest_judge.write_verifier) and the legacy snapshot verifier
    produced. The weighted branch used to emit only reward.json + detail.json,
    so downstream tooling reading verifier/ lost ctrf.json and reward.txt; this
    restores them from the weighted result's traj_tests + component ledger."""
    from datetime import datetime, timezone

    vdir = os.path.join(str(out_dir), "verifier")
    os.makedirs(vdir, exist_ok=True)

    tt = result.get("traj_tests") or {}
    passed = tt.get("passed_tests") or {}
    # Per-test weights from test_weights.json (components.traj_tests.tests) so a
    # guard (negative weight) reads as "passed" when it did NOT trigger.
    tw = {}
    if grading_dir:
        try:
            raw = json.load(open(os.path.join(str(grading_dir), "test_weights.json"),
                                 encoding="utf-8"))
            tw = ((raw.get("components") or {}).get("traj_tests") or {}).get("tests") or {}
        except (OSError, json.JSONDecodeError, AttributeError):
            tw = {}

    tests = []
    for name, is_pass in passed.items():
        w = tw.get(name, 1)
        triggered = bool(is_pass)
        status = ("passed" if triggered else "failed") if w >= 0 \
            else ("failed" if triggered else "passed")           # guard polarity
        tests.append({"name": name, "status": status,
                      "extra": {"weight": w, "kind": "goal" if w >= 0 else "guard"}})
    for c in (result.get("rubric_per_criterion") or []):
        tests.append({"name": f"rubric.{c.get('number')}",
                      "status": "passed" if c.get("satisfied") else "failed",
                      "extra": {"criterion": c.get("criterion")}})
    n_pass = sum(1 for t in tests if t["status"] == "passed")
    ctrf = {"results": {
        "tool": {"name": "complexmcp-weighted"},
        "summary": {"tests": len(tests), "passed": n_pass,
                    "failed": len(tests) - n_pass, "pending": 0, "skipped": 0,
                    "other": 0, "start": 0,
                    "stop": int(datetime.now(timezone.utc).timestamp())},
        "tests": tests,
    }}

    state = result.get("state") or {}
    reward = {
        "reward": result.get("reward"),
        "passed": result.get("passed"),
        "quadrant": result.get("quadrant"),
        "completion_rate": state.get("Rc"),
        "misbehaving_rate": state.get("Rb"),
        "components": result.get("components"),
        "earned": result.get("earned"),
        "penalty": result.get("penalty"),
        "pos_total": result.get("pos_total"),
        "grader": result.get("grader"),
    }

    with open(os.path.join(vdir, "reward.json"), "w", encoding="utf-8") as f:
        json.dump(reward, f, indent=2, default=str)
    with open(os.path.join(vdir, "reward.txt"), "w", encoding="utf-8") as f:
        f.write(str(result.get("reward")))
    with open(os.path.join(vdir, "ctrf.json"), "w", encoding="utf-8") as f:
        json.dump(ctrf, f, indent=2, default=str)
    with open(os.path.join(vdir, "detail.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    return vdir


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
    grading_dir = env("GRADING_DIR", here)
    # The gold tool-DAG must go through load_gold so names are BARE and match the
    # (bare) predicted names -- passing solution/trajectory.json raw would compare
    # server-prefixed gold names against bare predictions and score graph_f1 = 0.
    task_dir = env("TASK_DIR") or os.path.dirname(os.path.abspath(grading_dir.rstrip("/")))
    from benchmark.graph_judge import load_gold, _bare
    gold_plan = load_gold(task_dir)
    if gold_plan is None:
        raw = _load(env("GOLD_PLAN")) or _load(os.path.join(grading_dir, "gold_plan.json"))
        if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "tool" in raw[0]:
            # solution-plan shape (a flat list of {tool, args}) -> gold-DAG shape.
            gold_plan = [[{"server_name": "", "tool_name": _bare(s.get("tool")),
                           "dependencies": []}] for s in raw if s.get("tool")]
        else:
            gold_plan = raw  # already in gold_plan.json shape, or None
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
