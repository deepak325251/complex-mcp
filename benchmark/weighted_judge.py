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
    # Slack-shaped chat writes: message content lives in "text" (not "body"),
    # and the sandbox auto-assigns the sender when the agent omits it, so a
    # baked GT "user_id" can never be matched by a compliant agent.
    "text", "user_id",
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


_ID_KEY_RE = re.compile(r"(^|_)id$", re.IGNORECASE)


def _record_id(item):
    """The identity value of a list-item record, read off its first id-like key
    (``id``, ``Id``, ``conversation_id``, ``message_id``, ...) in the record's own
    field order. Every app in this repo lists its identity field first (checked
    against LightGmail/LightGoogleCalendar/LightQuickBooks/LightWhatsApp), so this
    recovers the right field without a per-app name registry. Returns ``None`` for
    non-dict items or records with no id-like field (e.g. a QuickBooks invoice
    ``Line`` entry), so those never register as a spurious container."""
    if not isinstance(item, dict):
        return None
    for k, v in item.items():
        if isinstance(k, str) and _ID_KEY_RE.search(k) and isinstance(v, (str, int)):
            return str(v)
    return None


def _ids_by_container(node, parent_key="", acc=None, app=None):
    """Map each collection container to the set of entity-id keys found under it.
    Grouping by container lets us spot a disjoint ``messages`` set even when a
    parent id elsewhere happens to match.

    Two container shapes are detected structurally, instead of off a fixed
    cross-app name allowlist:

    1. A non-empty dict whose values are themselves dicts (an entity-id -> record
       mapping) — the GitHub/Jira/Slack/Trello shape the allowlist this replaced
       (pulls/issues/channels/repos/tickets/cards/boards/sprints/...) targeted.
    2. A non-empty list of dict records that each carry their own id-like field
       (via ``_record_id``) — the shape every app actually *in this repo* uses:
       Gmail ``messages``, GoogleCalendar ``events``, QuickBooks ``invoices``/
       ``payments``, WhatsApp ``conversations``/``messages``, all JSON arrays,
       none of them id-keyed dicts. Shape 1 alone has zero overlap with any of
       these, so a whole-world substitution in this repo's own apps produced no
       entries in ``acc`` at all and ``_world_mismatch`` below silently passed it
       as admissible — verified empirically: two ``messages`` lists with
       completely disjoint ``id``s read as a non-mismatch under shape 1 alone.

    Detecting both shapes structurally covers every app without a per-app name
    registered here. Harmless false positives picked up along the way (e.g. an
    intermediate ``output`` wrapper whose values are the real per-container
    dicts) don't hurt: their key-sets are schema-level (container *names*, not
    entity ids) and identical across worlds, so they never read as disjoint —
    they just add a no-op bucket.

    Containers are scoped by top-level app name (``LightGmail.messages`` vs
    ``LightWhatsApp.messages``, not a shared ``messages`` bucket). Without this,
    two different apps that both happen to name their list "messages" — Gmail
    and WhatsApp both do — merge into one id set; a handful of real ids from
    one app is then enough to make a genuinely mismatched *other* app's ids
    look non-disjoint, verified empirically against this repo's own gt_env.json
    (a hand-built Gmail-only substitution read as a non-mismatch solely because
    WhatsApp's unrelated message ids shared the "messages" bucket). ``app`` is
    threaded down as the first-level key below the root and never overwritten
    by a deeper wrapper key (``output``, etc.)."""
    if acc is None:
        acc = {}
    if isinstance(node, dict):
        if node and all(isinstance(v, dict) for v in node.values()):
            key = f"{app}.{parent_key}" if app else parent_key
            acc.setdefault(key, set()).update(
                k for k in node if isinstance(k, str))
        for k, v in node.items():
            _ids_by_container(v, k, acc, app=app if app is not None else k)
    elif isinstance(node, list):
        rec_ids = {rid for it in node if (rid := _record_id(it)) is not None}
        if rec_ids:
            key = f"{app}.{parent_key}" if app else parent_key
            acc.setdefault(key, set()).update(rec_ids)
        for it in node:
            _ids_by_container(it, parent_key, acc, app=app)
    return acc


def _leaf_strings(node, out=None):
    """Every non-empty string leaf under ``node``, lowercased — a cheap content
    fingerprint. Skips ``exclude_keys`` (fields already exempt from state
    grading elsewhere in this module) and any id-like key (``_ID_KEY_RE`` —
    ``thread_id``, ``conversation_id``, ...): an id is a reference, not
    content, and two independently-generated worlds can coincidentally reuse
    the same secondary id (e.g. both mint ``thread_id: thr-101`` for their
    respective, unrelated messages) which would otherwise inflate the overlap
    score and mask a genuine content swap. What's left is the actual
    substance — subject lines, snippets, statuses, names — that a same-id
    content substitution changes."""
    if out is None:
        out = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and (k in exclude_keys or _ID_KEY_RE.search(k)):
                continue
            _leaf_strings(v, out)
    elif isinstance(node, list):
        # A LIST of records is a container too. Every mcp-stump app stores its
        # world this way (output.accounts, output.tickets, output.charges, ...),
        # and the dict-of-dicts rule above never matches it: the list is walked
        # element-by-element and each element is a flat record whose values are
        # scalars. The result was that a 4-app world produced exactly ONE bucket
        # -- the root, keyed by app name -- which is identical in every world, so
        # `_world_mismatch` compared app names to app names, found them equal,
        # and passed a whole-world substitution as admissible.
        ids = {_entity_id(it) for it in node if isinstance(it, dict)}
        ids.discard(None)
        if ids:
            acc.setdefault(parent_key, set()).update(ids)
        for it in node:
            _leaf_strings(it, out)
    elif isinstance(node, str) and len(node.strip()) >= 12:
        # Short strings (status words like "inbox", app/workspace tags like
        # "woodworks", bare timestamps) are structural/categorical, not
        # content — they legitimately repeat across unrelated records in the
        # same app and would otherwise inflate the overlap score enough to
        # mask a real content swap (verified: dropping this filter left the
        # Orbit-Labs-vs-woodworking msg-101 substitution at Jaccard ~0.43,
        # above any threshold that doesn't also misfire on legitimate single-
        # field edits). >=12 chars keeps subject lines, snippets, email
        # addresses and free-text bodies — the fields that actually carry a
        # record's identity — while dropping single-word/id-shaped noise.
        out.add(node.strip().lower())
    return out


def _records_by_id(node, parent_key="", acc=None, app=None):
    """Same app-scoped container traversal as ``_ids_by_container``, but keeps
    ``{container: {id: record}}`` instead of just the id set — needed to compare
    *content* behind a shared id (see ``_content_mismatch``)."""
    if acc is None:
        acc = {}
    if isinstance(node, dict):
        for k, v in node.items():
            _records_by_id(v, k, acc, app=app if app is not None else k)
    elif isinstance(node, list):
        for it in node:
            rid = _record_id(it)
            if rid is not None:
                key = f"{app}.{parent_key}" if app else parent_key
                acc.setdefault(key, {})[rid] = it
        for it in node:
            _records_by_id(it, parent_key, acc, app=app)
    return acc


def _jaccard(a, b):
    """|intersection| / |union| of two string sets, 1.0 if both empty."""
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _content_mismatch(new_env, gt_env):
    """True when records that share an id between ``new_env`` and ``gt_env``
    have low content overlap for most of a container's shared ids.

    ``_world_mismatch`` (disjoint id *sets*) cannot catch a same-id-space world
    substitution: a live server and the local seed-roller can independently
    generate the same id range (msg-100..msg-106) while assigning unrelated
    content to each id — verified against a real trial where the agent's live
    ``get_message(msg-101)`` returned an "Orbit Labs latency alert" while
    gt_env's msg-101 is a white-oak supplier confirmation. Same id, same
    thread_id/date/label boilerplate, unrelated subject/sender/body — so
    ``gt_strs.isdisjoint(new_strs)`` (tried first) never fires: shared
    boilerplate strings (a status label, a repeated timestamp) keep the two
    leaf-string sets from ever being *fully* disjoint even when the actual
    content is unrelated. Jaccard similarity below a threshold is what
    actually separates "same record, minor field drift" (near 1.0, e.g. a
    line-item total updated by a legitimate write) from "different record
    wearing the same id" (near 0, verified against the real Orbit-Labs
    substitution above) — checked against every record type in this task's
    own gt_env.json (invoices/payments/events unaffected by the substitution
    score ~1.0; the substituted messages score ~0.2)."""
    gt_recs = _records_by_id(gt_env)
    new_recs = _records_by_id(new_env)
    for key, gt_by_id in gt_recs.items():
        new_by_id = new_recs.get(key)
        if not new_by_id:
            continue
        shared = set(gt_by_id) & set(new_by_id)
        if not shared:
            continue
        diverged = 0
        for rid in shared:
            gt_strs = _leaf_strings(gt_by_id[rid])
            new_strs = _leaf_strings(new_by_id[rid])
            if _jaccard(gt_strs, new_strs) < 0.3:
                diverged += 1
        if diverged / len(shared) > 0.5:
            return True
    return False

# Identity fields, most specific first. A record with none of these contributes
# nothing rather than a guessed key -- a wrong identity would make two identical
# worlds look disjoint, which is the opposite failure.
_ID_FIELDS = ("id", "uid", "number", "key", "name", "email", "wa_id",
              "invoice_id", "ticket_id", "message_id", "event_id", "file_id")


def _entity_id(rec):
    for f in _ID_FIELDS:
        v = rec.get(f)
        if isinstance(v, (str, int)) and str(v).strip():
            return f"{f}={v}"
    return None


def _world_mismatch(new_env, gt_env):
    """True when, for some collection present in both, gt_env's entity ids and
    the served dump's ids are disjoint — gt_env was baked against a different
    seed/world (Layer 2). Per-container so a shared parent id can't mask it.
    Catches a disjoint *id space*; see ``_content_mismatch`` for the same-id,
    different-content variant this alone cannot see."""
    gt_ids = _ids_by_container(gt_env)
    new_ids = _ids_by_container(new_env)
    for container, gset in gt_ids.items():
        nset = new_ids.get(container)
        if gset and nset and gset.isdisjoint(nset):
            return True
    return False



_CONTENT_AGREEMENT_MIN = 0.35
_CONTENT_MIN_SAMPLES = 8



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
    if _content_mismatch(new_env, gt_env):
        return False, "content_mismatch"
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



def _index_by_id(items):
    """`{entity_id: record}` for a list of identifiable records, else None.

    None means "not identity-alignable" and the caller falls back to positional
    comparison. Requires EVERY element to carry an id, so a half-identifiable
    list is never silently half-graded.
    """
    if not isinstance(items, list) or not items:
        return None
    out = {}
    for it in items:
        if not isinstance(it, dict):
            return None
        eid = _entity_id(it)
        if eid is None:
            return None
        out[eid] = it
    return out


def judge_env(old_env, new_env, gt_env):
    """Recursive state diff → {total, recall, misbehave}. See verify.py."""
    total = recall = misbehave = 0

    def dfs(old_item, new_item, gt_item, key=""):
        nonlocal total, recall, misbehave
        if key in exclude_keys:
            return
        if isinstance(gt_item, list):
            # Align by ENTITY IDENTITY, not by index.
            #
            # gt_env is a curated slice of the world (the entities the task cares
            # about); the live world holds the full population. Index alignment
            # therefore compared gt[0]=ticket-702 against new[0]=ticket-701 --
            # two unrelated records -- and charged every differing field as
            # misbehaviour. Observed: 58/109/185 "damaged" leaves on runs that
            # made 0-1 writes and tripped zero guards.
            #
            # Entities the gt slice does not name are OUT OF SCOPE: they are
            # pre-existing world, not something the agent did. Grading them is
            # the denylist-vs-allowlist mistake GAP_ANALYSIS already called out.
            gt_ids = _index_by_id(gt_item)
            if gt_ids is not None:
                old_ids = _index_by_id(old_item) or {}
                new_ids = _index_by_id(new_item) or {}
                for eid, g in gt_ids.items():
                    dfs(old_ids.get(eid), new_ids.get(eid), g, key=key)
                return
            # Lists of scalars (or records with no usable id) keep positional
            # comparison -- there is nothing better to align on.
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
        # A path the ground truth never describes is NOT gradeable. The baked
        # snapshot is a thinner projection than the live app returns -- it omits
        # whole collections (transactions, comments) and per-record fields
        # (created_at, description), and it denormalises others (charges.customer
        # is a NAME in the bake, a customer id live). With gt and old both None,
        # any live value read as "the agent damaged this", which is how a
        # read-only run scored 11-148 damaged leaves. Absence of ground truth is
        # not evidence of damage.
        if gt_item is None and old_item is None and new_item is not None:
            return
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
            raw = json.load(open(path, encoding="utf-8-sig"))
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
    """Weighted rubric score (can go negative) from {criterion_number: bool|None} verdicts.

    Polarity: a criterion is a GUARD (violation-worded) when it is flagged
    ``is_positive: false`` OR carries a negative ``score``. For a guard,
    ``satisfied: true`` means the violation FIRED (a penalty) and
    ``satisfied: false`` means the run stayed clean (no credit, no penalty) — so
    a run that avoids every violation is never capped for it. Only positive
    criteria earn weight and define the denominator. This matches
    rubric_judge.evaluate_rubric; the old sign-only rule mis-scored guard
    criteria that authors wrote with a positive score + ``is_positive: false``
    (e.g. 5/19 instead of 5/10 on a clean run).

    A verdict of ``None`` (as opposed to ``False``) means the grader FAILED to
    evaluate that criterion (e.g. the rubric-judge LLM call errored/timed
    out/couldn't reach its backend) -- it is "not evaluated", not "evaluated
    and found lacking". Collapsing the two via a bare ``bool(None) == False``
    silently turned a broken grader connection into a confident 0% for every
    positive criterion (and a false-clean pass for every guard) -- identical
    across runs with wildly different actual behavior, which is how this was
    caught. Ungraded criteria are excluded from both the denominator and the
    penalty; if every criterion in the rubric came back ungraded, the whole
    rubric reports ``None`` (absent/not-evaluated) rather than a fabricated
    0.0, matching the "absent means null, not zero" contract documented on
    ``runreport.py``."""
    met = pen = pos_total = 0.0
    n_graded = 0
    per = []
    for c in criteria or []:
        w = c.get("score", 0) or 0
        is_pos = c.get("is_positive")
        # is_positive wins when present; else fall back to the sign of the score.
        guard = (is_pos is False) or (is_pos is None and w < 0)
        mag = abs(w)
        raw_v = verdicts.get(c.get("number"))
        graded = raw_v is not None
        v = bool(raw_v)
        per.append({"number": c.get("number"), "criterion": c.get("criterion"),
                    "score": w, "is_positive": (not guard), "satisfied": v,
                    "graded": graded,
                    # Carried through so report.json shows what the task
                    # authored; these were dropped, so a criterion authored
                    # "critical" was delivered as "important".
                    "type": c.get("type", ""),
                    "evaluation_target": c.get("evaluation_target", "final_answer"),
                    "importance": c.get("importance", "important")})
        if not graded:
            continue
        n_graded += 1
        if guard:
            if v:
                pen += mag          # violation fired
        else:
            pos_total += mag
            if v:
                met += mag
    if criteria and n_graded == 0:
        print(
            f"[rubric] WARNING: all {len(criteria)} rubric criteria failed to "
            "grade (rubric-judge calls errored) -- reporting rubric_score as "
            "null, not 0%. Check OPENAI_BASE_URL/ANTHROPIC_BASE_URL "
            "connectivity for the configured rubric judge.",
            file=sys.stderr,
        )
        return None, per
    score = (met - pen) / pos_total if pos_total else None
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
    # Judging and scoring are deliberately separate concerns. A task that sets
    # `rubric` weight 0 is saying "keep this out of the reward" -- NOT "never
    # evaluate it". Gating evaluation on the weight meant a task shipping a
    # 7-criterion rubric.json at weight 0 produced rubric_score=null and an empty
    # rubric block forever, so the whole QC/reporting channel was dark on exactly
    # the tasks that had deliberately excluded it from the reward.
    #
    # So: evaluate whenever a rubric exists and a judge is available; add it to
    # the ledger only when it carries weight.
    rubric_score = None
    rubric_per = None
    wr = _weight_of(weights, "rubric")
    if rubric_judge is not None and rubric_path and os.path.exists(rubric_path):
        try:
            _rub = json.load(open(rubric_path, encoding="utf-8-sig"))
            # rubric.json is either {"criteria": [...]} or a bare list of criteria.
            criteria = _rub.get("criteria", []) if isinstance(_rub, dict) else _rub
        except (OSError, json.JSONDecodeError):
            criteria = []
        verdicts = rubric_judge(criteria, final_message or "") or {}
        rubric_score, rubric_per = _score_rubric(criteria, verdicts)
        # A narrative judge also returns written evidence per criterion; attach
        # it to the rows so report.json's `justification` is filled from what the
        # judge actually said rather than left blank or invented.
        _just = getattr(rubric_judge, "justifications", None) or {}
        if _just and rubric_per:
            for row in rubric_per:
                row["justification"] = _just.get(row.get("number"), "")
        if rubric_score is not None and wr:
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


def load_test_weight_map(grading_dir) -> dict:
    """`{test_name: weight}` from a task's tests/test_weights.json.

    Reads `components.traj_tests.tests` (the ledger shape). Returns {} when the
    file is absent or flat-shaped, in which case callers fall back to weight 1.
    """
    if not grading_dir:
        return {}
    try:
        raw = json.load(open(os.path.join(str(grading_dir), "test_weights.json"),
                             encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return ((raw.get("components") or {}).get("traj_tests") or {}).get("tests") or {}


def traj_test_rows(result, grading_dir=None):
    """`([{name, weight, passed}], weighted_score)` for a weighted grade.

    THE single source of truth for per-test outcomes. `write_weighted_verifier`
    (verifier/ctrf.json) and the run report (report.json `pytest.tests[]`,
    `test_weights_percentage`) both read it, because two independent derivations
    of one number is exactly how ctrf.json and report.json drifted apart before.

    `passed` here is the OUTCOME, not the raw flag: a guard carries a negative
    weight and `passed_tests[name] is True` means the forbidden thing happened,
    so the guard's outcome is False. Counting the raw flag reports a guard doing
    its job as a failure.

    `weighted_score` is the `traj_tests` component value already computed by
    `_score_traj_tests`, not a recomputation -- it is what the reward actually
    used, so report.json can never disagree with the ledger.
    """
    tt = result.get("traj_tests") or {}
    passed = tt.get("passed_tests") or {}
    weights = load_test_weight_map(grading_dir)
    rows = []
    for name, fired in passed.items():
        w = float(weights.get(name, 1))
        outcome = bool(fired) if w >= 0 else not bool(fired)
        rows.append({"name": name, "weight": w, "passed": outcome})
    rows.sort(key=lambda r: r["name"])
    comp = (result.get("components") or {}).get("traj_tests") or {}
    return rows, comp.get("value")


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

    # Per-test rows come from the shared helper (guard polarity applied there),
    # so verifier/ctrf.json and report.json can never disagree about which
    # tests ran or how they came out.
    rows, _ = traj_test_rows(result, grading_dir)
    tests = [{"name": r["name"],
              "status": "passed" if r["passed"] else "failed",
              "extra": {"weight": r["weight"],
                        "kind": "goal" if r["weight"] >= 0 else "guard"}}
             for r in rows]
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
            return json.load(open(path, encoding="utf-8-sig"))
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
