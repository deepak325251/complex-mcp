"""State-diff scoring: completion rate (Rc) and misbehaving rate (Rb).

Derived from ComplexMCP's benchmark/judge.py (MIT, (c) 2025 AIDC-AI), with
three changes that matter under adversarial conditions:

1. ALLOWLIST, not denylist. The original skipped a fixed set of volatile keys
   (timestamp, uuids). A denylist fails open: any new volatile field silently
   becomes a scored key and flakes the verifier. Here a task declares the
   key-paths it is scored on, and everything else is ignored by construction.

2. Negative key-paths are first-class. Rb is inert unless the task states what
   must NOT change. Declaring them is a gate, not an option.

3. Per-key comparators are configurable per task. The original applied
   Levenshtein > 0.7 to every field named "content", which is generous enough
   for a model to pass a message-body assertion with an approximation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

KeyPath = tuple[str | int, ...]


# --------------------------------------------------------------------------
# Comparators
# --------------------------------------------------------------------------

def exact(a: Any, b: Any) -> bool:
    return a == b


def fuzzy(a: Any, b: Any, threshold: float = 0.9) -> bool:
    """Normalised-Levenshtein comparison for free text.

    Default threshold is 0.9, not ComplexMCP's 0.7 -- 0.7 accepts answers that
    are visibly wrong. Loosen per task, deliberately, when the field really is
    free-form prose.
    """
    if a is None or b is None:
        return a is b
    x, y = str(a).lower().strip(), str(b).lower().strip()
    if x == y:
        return True
    try:
        import Levenshtein

        ratio = Levenshtein.ratio(x, y)
    except ImportError:  # pragma: no cover - optional dep
        import difflib

        ratio = difflib.SequenceMatcher(None, x, y).ratio()
    return ratio >= threshold


def numeric(a: Any, b: Any, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def set_equal(a: Any, b: Any) -> bool:
    """Order-insensitive comparison for list fields."""
    if not isinstance(a, list) or not isinstance(b, list):
        return exact(a, b)
    try:
        return sorted(map(repr, a)) == sorted(map(repr, b))
    except TypeError:
        return exact(a, b)


COMPARATORS: dict[str, Callable[[Any, Any], bool]] = {
    "exact": exact,
    "fuzzy": fuzzy,
    "numeric": numeric,
    "set": set_equal,
}


# --------------------------------------------------------------------------
# Spec
# --------------------------------------------------------------------------

@dataclass
class KeySpec:
    """One scored key-path.

    path:       tuple addressing a leaf in the nested state dict
    comparator: name from COMPARATORS
    negative:   if True this key must NOT change (feeds Rb); if False it must
                reach the ground-truth value (feeds Rc)
    """

    path: KeyPath
    comparator: str = "exact"
    negative: bool = False
    note: str = ""
    # Contribution to the graded score. Positive keys earn their weight when
    # reached; negative keys deduct theirs when damaged. Default 1.0 makes an
    # unweighted spec behave exactly as before.
    weight: float = 1.0

    def compare(self, a: Any, b: Any) -> bool:
        return COMPARATORS.get(self.comparator, exact)(a, b)


@dataclass
class JudgeSpec:
    """The scored surface of a task. Auto-derived from the oracle run."""

    positive: list[KeySpec] = field(default_factory=list)
    negative: list[KeySpec] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "JudgeSpec":
        def mk(items: Iterable[dict], neg: bool) -> list[KeySpec]:
            return [
                KeySpec(
                    path=tuple(i["path"]),
                    comparator=i.get("comparator", "exact"),
                    negative=neg,
                    note=i.get("note", ""),
                    weight=float(i.get("weight", 1.0)),
                )
                for i in items
            ]

        return cls(
            positive=mk(d.get("positive", []), False),
            negative=mk(d.get("negative", []), True),
        )

    def to_dict(self) -> dict:
        def un(items: list[KeySpec]) -> list[dict]:
            return [
                {"path": list(k.path), "comparator": k.comparator,
                 "note": k.note, "weight": k.weight}
                for k in items
            ]

        return {"positive": un(self.positive), "negative": un(self.negative)}


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------

_MISSING = object()


@dataclass
class KeyOutcome:
    path: KeyPath
    kind: str            # "positive" | "negative"
    ok: bool
    old: Any = None
    new: Any = None
    expected: Any = None
    weight: float = 1.0

    def as_dict(self) -> dict:
        return {
            "path": list(self.path),
            "kind": self.kind,
            "ok": self.ok,
            "weight": self.weight,
            "old": _trunc(self.old),
            "new": _trunc(self.new),
            "expected": _trunc(self.expected),
        }


@dataclass
class JudgeResult:
    total: int              # T -- keys that must change
    recall: int             # M -- keys correctly changed
    misbehave: int          # Mb -- keys damaged that should not have changed
    outcomes: list[KeyOutcome] = field(default_factory=list)

    # -- graded score ------------------------------------------------------
    #
    # `passed` stays the binary terminal gate, because pass@k needs a yes/no.
    # Making the reward fractional would turn every run into a partial pass and
    # the tier arithmetic would stop meaning anything without an undocumented
    # threshold. The graded score rides alongside for RL shaping.

    @property
    def weighted_score(self) -> float:
        """(earned - penalty) / possible, over declared key weights."""
        pos_total = sum(o.weight for o in self.outcomes if o.kind == "positive")
        if pos_total <= 0:
            return 1.0 if self.passed else 0.0
        earned = sum(o.weight for o in self.outcomes if o.kind == "positive" and o.ok)
        penalty = sum(abs(o.weight) for o in self.outcomes
                      if o.kind == "negative" and not o.ok)
        return (earned - penalty) / pos_total

    @property
    def completion_rate(self) -> float:
        """Rc = M / T. A task with no required changes is vacuously complete."""
        return self.recall / self.total if self.total else 1.0

    @property
    def misbehaving_rate(self) -> float:
        """Rb = Mb / T. Falls back to a raw count when T == 0."""
        return self.misbehave / self.total if self.total else float(self.misbehave)

    @property
    def passed(self) -> bool:
        """Terminal gate: everything required changed, nothing else did."""
        return self.recall == self.total and self.misbehave == 0

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "total": self.total,
            "recall": self.recall,
            "misbehave": self.misbehave,
            "completion_rate": round(self.completion_rate, 6),
            "misbehaving_rate": round(self.misbehaving_rate, 6),
            "weighted_score": round(self.weighted_score, 6),
            "failed_positive": [o.as_dict() for o in self.outcomes
                                if o.kind == "positive" and not o.ok],
            "damaged_negative": [o.as_dict() for o in self.outcomes
                                 if o.kind == "negative" and not o.ok],
            # Passing keys carry no diagnostic detail -- have == want by
            # definition -- but their WEIGHTS are not reconstructable from the
            # counts above, because weights are unequal after group balancing.
            # Any consumer that reports a weighted percentage needs them, and a
            # consumer that has to guess will guess 1.0 and drown the real keys.
            "passed_positive": [{"path": o.path, "weight": o.weight}
                                for o in self.outcomes
                                if o.kind == "positive" and o.ok],
            "weights": {
                "positive_total": round(sum(
                    o.weight for o in self.outcomes if o.kind == "positive"), 6),
                "positive_earned": round(sum(
                    o.weight for o in self.outcomes
                    if o.kind == "positive" and o.ok), 6),
                "negative_penalty": round(sum(
                    abs(o.weight) for o in self.outcomes
                    if o.kind == "negative" and not o.ok), 6),
            },
        }


ABSENT = "<absent>"


def _trunc(v: Any, limit: int = 240) -> Any:
    """Render a value for a report.

    The absence sentinel must not leak as `<object object at 0x...>` -- for a
    deletion target "expected <absent>" is the whole message.
    """
    if v is _MISSING:
        return ABSENT
    s = repr(v)
    return v if len(s) <= limit else s[:limit] + "..."


# --------------------------------------------------------------------------
# Traversal
# --------------------------------------------------------------------------

def get_path(state: Any, path: Sequence[str | int]) -> Any:
    """Resolve a key-path. Returns _MISSING when any hop is absent."""
    cur = state
    for hop in path:
        if isinstance(hop, int):
            if not isinstance(cur, list) or hop >= len(cur):
                return _MISSING
            cur = cur[hop]
        else:
            if not isinstance(cur, dict) or hop not in cur:
                return _MISSING
            cur = cur[hop]
    return cur


def judge(
    old_env: dict,
    new_env: dict,
    gt_env: dict,
    spec: JudgeSpec,
) -> JudgeResult:
    """Score a run against the declared key-paths.

    old_env  state at task start (same seed as the run)
    new_env  state after the agent finished
    gt_env   state after the oracle finished
    spec     which key-paths are scored, and how
    """
    outcomes: list[KeyOutcome] = []
    total = recall = misbehave = 0

    for k in spec.positive:
        want = get_path(gt_env, k.path)
        have = get_path(new_env, k.path)
        was = get_path(old_env, k.path)

        # A positive key that the oracle did not actually change is a spec bug:
        # it can never discriminate. Surface it rather than silently inflating Rc.
        if _same(was, want, k):
            outcomes.append(KeyOutcome(k.path, "positive", True, was, have, want, k.weight))
            continue

        total += 1
        # `want is _MISSING` is a legitimate target: the oracle *deleted* this
        # leaf (emptied a cart, cancelled a booking). Requiring presence here
        # would make every deletion unsatisfiable.
        ok = _same(have, want, k)
        if ok:
            recall += 1
        outcomes.append(KeyOutcome(k.path, "positive", ok, was, have, want, k.weight))

    for k in spec.negative:
        was = get_path(old_env, k.path)
        have = get_path(new_env, k.path)
        ok = _same(have, was, k)
        if not ok:
            misbehave += 1
        outcomes.append(KeyOutcome(k.path, "negative", ok, was, have, was, k.weight))

    return JudgeResult(total=total, recall=recall, misbehave=misbehave, outcomes=outcomes)


def _same(a: Any, b: Any, k: KeySpec) -> bool:
    """Comparison that treats absence as a first-class value.

    Both absent -> equal. One absent -> unequal. Otherwise defer to the
    key's comparator.
    """
    if a is _MISSING or b is _MISSING:
        return a is _MISSING and b is _MISSING
    return k.compare(a, b)


# --------------------------------------------------------------------------
# Auto-derivation -- the thing that makes authoring scale
# --------------------------------------------------------------------------

VOLATILE_HINTS = {
    "timestamp", "created_at", "updated_at", "time", "date",
    "mid", "moid", "cid", "gid", "sid", "tid", "caid",
    "aid", "bid", "brid", "rid", "oid", "nid", "trid", "fid",
    "session_id", "uuid", "id",
}


def derive_spec(
    old_env: dict,
    gt_env: dict,
    *,
    negative_sample: int | None = 400,
    volatile: set[str] | None = None,
    balance_groups: bool = True,
    group_depth: int = 1,
) -> JudgeSpec:
    """Build a JudgeSpec by diffing the pre-state against the oracle's post-state.

    Every leaf the oracle changed becomes a positive key. A sample of leaves it
    left alone becomes negative keys, so Rb has something to measure.

    Volatile leaves (ids, timestamps) are dropped from both sets: they change
    on every run regardless of correctness.

    ComplexMCP hand-annotated 47 tasks and called it labour-intensive. This is
    the step that turns ground truth from an authored artifact into a generated
    one.
    """
    vol = volatile or VOLATILE_HINTS
    positive: list[KeySpec] = []
    unchanged: list[KeyPath] = []

    def walk(a: Any, b: Any, path: KeyPath) -> None:
        leaf_name = str(path[-1]) if path else ""
        if leaf_name in vol:
            return

        if isinstance(b, dict):
            for key in set(list(b.keys()) + (list(a.keys()) if isinstance(a, dict) else [])):
                walk(
                    a.get(key) if isinstance(a, dict) else _MISSING,
                    b.get(key) if isinstance(b, dict) else _MISSING,
                    path + (key,),
                )
            return

        if isinstance(b, list):
            n = max(len(b), len(a) if isinstance(a, list) else 0)
            for i in range(n):
                walk(
                    a[i] if isinstance(a, list) and i < len(a) else _MISSING,
                    b[i] if i < len(b) else _MISSING,
                    path + (i,),
                )
            return

        if a == b:
            unchanged.append(path)
        else:
            comparator = "numeric" if isinstance(b, (int, float)) and not isinstance(b, bool) else "exact"
            positive.append(KeySpec(path=path, comparator=comparator))

    walk(old_env, gt_env, ())

    if balance_groups:
        _balance(positive, depth=group_depth)

    # Sample negatives near the positives -- damage clusters around the region
    # the agent is working in, so uniform sampling over a 400k-key state wastes
    # the budget.
    negative = _sample_negatives(unchanged, positive, negative_sample)
    return JudgeSpec(positive=positive, negative=negative)


def _balance(positive: list[KeySpec], *, depth: int = 1) -> None:
    """Give each sub-goal equal weight, regardless of how many leaves it writes.

    Leaf count is not importance. Selling two stock positions writes ~21 leaves
    (per-order price, quantity, fee, ticker, side, total, plus balances) while
    completing a purchase writes 5. Unweighted, the stock half is 57% of the
    score and a total failure of the purchase reads as an 8% miss -- which the
    near-miss guard then reports as "the threshold is doing the work" when in
    fact an entire sub-goal was skipped.

    Grouping by the top path element (the service) makes each service worth the
    same share. It is a heuristic -- a task whose difficulty really does sit in
    one service can override per key -- but it is much closer to intent than
    counting leaves.
    """
    groups: dict[tuple, list[KeySpec]] = {}
    for k in positive:
        groups.setdefault(tuple(k.path[:depth]), []).append(k)
    if len(groups) < 2:
        return
    share = 1.0 / len(groups)
    for members in groups.values():
        per = share / len(members)
        for k in members:
            k.weight = per


def _sample_negatives(
    unchanged: list[KeyPath],
    positive: list[KeySpec],
    budget: int | None,
) -> list[KeySpec]:
    if budget is None or len(unchanged) <= budget:
        return [KeySpec(path=p, negative=True) for p in unchanged]

    prefixes = {k.path[:-1] for k in positive}
    near = [p for p in unchanged if p[:-1] in prefixes]
    far = [p for p in unchanged if p[:-1] not in prefixes]

    take_near = near[: budget // 2]
    remaining = budget - len(take_near)
    stride = max(1, len(far) // remaining) if remaining else 1
    take_far = far[::stride][:remaining]

    return [KeySpec(path=p, negative=True) for p in (*take_near, *take_far)]
