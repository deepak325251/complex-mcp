"""World-full assertions for pytest — the twin of traj_asserts.

Lets a task's test_outputs.py include a STATE-DIFF test case alongside its
world-free tool/answer checks, so grading is one uniform pytest suite:

    from benchmark import state_asserts as S

    def test_world_ends_correct():
        assert S.completion() == 1.0     # every required change happened (Rc)
        assert S.misbehave() == 0        # nothing protected was touched  (Rb)

    def test_meeting_bullet_present():   # targeted, human-readable variant
        assert S.new_at("LightNotion", "blocks")           # collection exists
        assert S.matches_gt("LightSlack", "channels")      # equals ground truth

The three world snapshots are staged by the harness at $COMPLEXMCP_OLD_ENV,
$COMPLEXMCP_NEW_ENV, $COMPLEXMCP_GT_ENV (all in the {app: {status, output}}
schema). completion()/misbehave() reuse the exact judge_env diff the weighted
grader uses, so the pytest verdict and the ledger agree by construction.
"""

import json
import os

from benchmark.weighted_judge import judge_env

_CACHE: dict = {}


def _load(var):
    if var not in _CACHE:
        p = os.environ.get(var)
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                _CACHE[var] = json.load(f)
        else:
            _CACHE[var] = {}
    return _CACHE[var]


def old():
    return _load("COMPLEXMCP_OLD_ENV")


def new():
    return _load("COMPLEXMCP_NEW_ENV")


def gt():
    return _load("COMPLEXMCP_GT_ENV")


def available() -> bool:
    """True when all three snapshots are present (else the state test should
    xfail/skip rather than assert against empty dicts)."""
    return bool(old()) and bool(new()) and bool(gt())


def diff() -> dict:
    """Raw {total, recall, misbehave} from the same judge_env the ledger uses."""
    return judge_env(old(), new(), gt())


def completion() -> float:
    """Rc in [0,1] — fraction of required world changes the agent achieved. 1.0
    when the world encodes no required change (a pure guardrail)."""
    d = diff()
    return (d["recall"] / d["total"]) if d["total"] else 1.0


def misbehave() -> int:
    """Rb count — protected/guarded state fields the agent changed (want 0)."""
    return diff()["misbehave"]


def solved() -> bool:
    """Terminal world-full gate: every required change made, nothing protected
    touched."""
    d = diff()
    return d["total"] > 0 and d["recall"] == d["total"] and d["misbehave"] == 0


# --- targeted path accessors (app -> output -> path) -----------------------
def _walk(env, app, *path):
    node = (env.get(app) or {}).get("output")
    for k in path:
        if isinstance(node, dict):
            node = node.get(k)
        elif isinstance(node, list) and isinstance(k, int) and -len(node) <= k < len(node):
            node = node[k]
        else:
            return None
    return node


def new_at(app, *path):
    return _walk(new(), app, *path)


def gt_at(app, *path):
    return _walk(gt(), app, *path)


def old_at(app, *path):
    return _walk(old(), app, *path)


def matches_gt(app, *path) -> bool:
    """The post-run world value at this path equals ground truth."""
    return _walk(new(), app, *path) == _walk(gt(), app, *path)


def unchanged(app, *path) -> bool:
    """The value at this path was NOT touched (new == old) — a guard check."""
    return _walk(new(), app, *path) == _walk(old(), app, *path)
