"""Equal Function Sets.

A gold plan node is not one tool, it is the set of tools that satisfy that step.
Without this, a model that picks a valid alternative is scored wrong -- a false
negative that is unlearnable in training data and, because it looks like
difficulty, corrupts the tier label too. It is the highest-cost defect in a
tool-calling corpus and the reason ETOM's contribution matters.

Reimplemented from the ETOM paper (arXiv:2510.19423), adapted in one important
way: ETOM verified equivalence against a *query*, because it had no execution.
We have the oracle's actual call, so equivalence is verified against the real
invocation -- the arguments the oracle used and the result it got. That is a
stronger test than paraphrase similarity.

Pipeline:
    1. candidates   lexical stem collision + shared argument shape
    2. verify       LLM pairwise, in the context of the oracle's real call
    3. group        Union-Find over verified pairs
    4. expand       widen every gold-plan node to its set

Verification is deliberately conservative: unproven pairs stay separate. A
missed equivalence costs a false negative on one alternative; a wrong one
accepts an incorrect answer forever.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

# Suffixes/prefixes that mark a variant of the same operation rather than a
# different operation.
_VARIANT_AFFIXES = (
    "fuzzy_", "_by_name", "_by_id", "_from_name", "_all",
)

# Affixes that change WHAT is acted on, not just how it is found. Tools that
# differ only by one of these are NOT candidates -- `send_message` and
# `send_message_to_group` address different entities.
_SCOPE_AFFIXES = (
    "_to_group", "_in_group", "_in_shop", "_group",
)


def stem(name: str) -> str:
    s = name
    for a in _VARIANT_AFFIXES:
        s = s.replace(a, "")
    return s.strip("_")


def scope(name: str) -> str:
    """The scope marker, if any. Different scope -> different operation."""
    for a in _SCOPE_AFFIXES:
        if a in name:
            return a
    return ""


@dataclass
class Tool:
    server: str
    name: str
    description: str = ""
    args: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return f"{self.server}::{self.name}"


@dataclass
class EFSIndex:
    """Resolved equivalence sets, keyed by tool id."""

    sets: list[set[str]] = field(default_factory=list)
    _lookup: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._reindex()

    def _reindex(self) -> None:
        self._lookup = {}
        for i, s in enumerate(self.sets):
            for t in s:
                self._lookup[t] = i

    def equivalents(self, tool_id: str) -> set[str]:
        """Every tool that satisfies the same step. Always includes the input."""
        i = self._lookup.get(tool_id)
        return set(self.sets[i]) if i is not None else {tool_id}

    def covered(self, tool_ids: Iterable[str]) -> dict[str, bool]:
        return {t: t in self._lookup for t in tool_ids}

    def to_dict(self) -> dict:
        return {
            "total_sets": len(self.sets),
            "total_tools": sum(len(s) for s in self.sets),
            "sets": [sorted(s) for s in self.sets],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EFSIndex":
        return cls(sets=[set(s) for s in d.get("sets", [])])

    @classmethod
    def load(cls, path: str | Path) -> "EFSIndex":
        p = Path(path)
        return cls.from_dict(json.loads(p.read_text())) if p.is_file() else cls()

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=1))
        return p


# --------------------------------------------------------------------------
# 1. candidate generation
# --------------------------------------------------------------------------

# Verb prefixes with opposite effect. `star_shop`/`unstar_shop` and
# `get_chat_history`/`delete_chat_history` have identical signatures and heavily
# overlapping prose, so signature+overlap alone proposes them. They are inverses,
# not alternatives -- treating them as equivalent would accept a destructive call
# as a valid substitute for a read.
_POLARITY = (
    ("un", ""), ("delete_", "get_"), ("delete_", "list_"), ("remove_", "get_"),
    ("remove_", "add_"), ("unstar_", "star_"), ("unlike_", "like_"),
    ("unblock_", "block_"), ("withdraw_", "comment_"), ("cancel_", "place_"),
    ("quit_", "create_"), ("mark_as_unread", "mark_as_read"),
)


def _opposed(a: str, b: str) -> bool:
    lo, hi = sorted((a, b))
    for neg, pos in _POLARITY:
        if not neg:
            continue
        if (lo.startswith(pos) and hi.startswith(neg)) or (hi.startswith(pos) and lo.startswith(neg)):
            return True
        if neg in lo and neg not in hi:
            return True
        if neg in hi and neg not in lo:
            return True
    return False


_STOP = {"a","an","the","of","for","to","in","on","by","with","and","or","from",
         "using","their","its","this","that","based","specific","specified","given",
         "return","returns","retrieve","retrieves","get","gets","list","lists"}


def _content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    out = set()
    for w in words:
        if w in _STOP or len(w) < 3:
            continue
        # De-plural at len>3, not len>4: the 4-letter case is exactly where it
        # matters ("uids" -> "uid", "ids" -> "id"). Getting this wrong dropped
        # get_uid_from_name ~ fuzzy_search_uids_from_name below threshold.
        if w.endswith("ss"):
            out.add(w)
        elif w.endswith("s") and len(w) > 3:
            out.add(w[:-1])
        else:
            out.add(w)
    return out


def _description_overlap(a: Tool, b: Tool) -> float:
    wa, wb = _content_words(a.description), _content_words(b.description)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def candidates(tools: Sequence[Tool], *, cross_server: bool = False,
               overlap_threshold: float = 0.25) -> list[tuple[Tool, Tool]]:
    """Pairs worth asking about.

    Two filters do most of the work:

      same stem      `search_items` / `fuzzy_search_items` are variants of one
                     operation; `list_items` / `delete_item` are not
      same scope     `send_message` and `send_message_to_group` share a stem
                     but address different entities, so they are excluded

    cross_server is off by default. `LightShop::check_balance` and
    `LightFlight::check_balance` read different accounts -- lexically identical,
    semantically unrelated. Enabling it is a per-corpus decision.
    """
    out: list[tuple[Tool, Tool]] = []
    for i, a in enumerate(tools):
        for b in tools[i + 1:]:
            if a.id == b.id:
                continue
            if not cross_server and a.server != b.server:
                continue
            if scope(a.name) != scope(b.name):
                continue

            # Signal 1: shared stem. Catches search/fuzzy_search variants.
            if stem(a.name) == stem(b.name):
                out.append((a, b))
                continue

            # Signal 2: identical argument signature + overlapping prose.
            # Stemming alone misses pairs like get_uid_from_name and
            # fuzzy_search_uids_from_name -- same inputs, same job, unrelated
            # names. ETOM used embeddings here; argument shape plus description
            # overlap is the cheap approximation, and every candidate is
            # verified downstream anyway.
            if _opposed(a.name, b.name):
                continue
            if a.args and a.args == b.args and _description_overlap(a, b) >= overlap_threshold:
                out.append((a, b))
    return out


# --------------------------------------------------------------------------
# 2. verification
# --------------------------------------------------------------------------

# Equivalence is CONDITIONED ON A STEP, not global.
#
# Asked in the abstract, `search_items` and `fuzzy_search_items` are distinct --
# exact versus approximate matching -- and a careful judge says so. Asked about
# a specific step where the oracle searched for "bottle gourd" and got a hit,
# either tool satisfies it. The first framing rejects every real equivalence and
# leaves the false-negative problem exactly where it was; this is ETOM's
# top-down, query-conditioned phase and it is the phase that matters.
VERIFY_PROMPT = """You are auditing a tool-calling benchmark for false negatives.

A reference solution performed the STEP below. A model attempting the same task
might reasonably use a different tool for that step. Your job is to decide
whether the alternative would ALSO satisfy this specific step -- not whether the
two tools are identical in general.

Answer SATISFIES if a model using TOOL B, with arguments appropriate to it,
would accomplish what the oracle accomplished with TOOL A at this step and leave
the task able to proceed. Differences in matching strategy (exact vs fuzzy),
result cardinality, or pagination do NOT make it distinct, provided the model
can still get what the step needs.

Answer DISTINCT if TOOL B acts on something else, causes a different side
effect, or could not supply what the next step depends on.

THE STEP (what the oracle actually did):
  {call}

TOOL A (what the oracle used): {a_id}
  description: {a_desc}
  arguments: {a_args}

TOOL B (the candidate alternative): {b_id}
  description: {b_desc}
  arguments: {b_args}

Reply with exactly one word on the first line: SATISFIES or DISTINCT.
On the second line, one sentence of justification."""


def verify_pair(a: Tool, b: Tool, call: str, ask) -> tuple[bool, str]:
    """Would `b` satisfy the step `a` was used for? `ask` returns model text.

    `call` is required in practice: without a concrete step this collapses back
    to the global question, which rejects everything.
    """
    reply = ask(VERIFY_PROMPT.format(
        a_id=a.id, a_desc=a.description, a_args=", ".join(a.args) or "(none)",
        b_id=b.id, b_desc=b.description, b_args=", ".join(b.args) or "(none)",
        call=call or "(no oracle call recorded for this pair)",
    ))
    first = (reply or "").strip().splitlines()
    verdict = first[0].strip().upper() if first else ""
    why = first[1].strip() if len(first) > 1 else ""
    return verdict.startswith(("SATISFIES", "EQUIVALENT")), why


def resolve_for_trace(
    gold_trace: Sequence[dict],
    tools: Sequence[Tool],
    ask,
    *,
    cross_server: bool = False,
    on_result=None,
) -> tuple[EFSIndex, list[dict]]:
    """Resolve equivalence per step of a gold trace.

    For every distinct tool the oracle used, propose alternatives and verify
    them against that oracle call. This is the query-conditioned phase: the same
    pair can satisfy one step and not another, and only the step-scoped answer
    is meaningful.
    """
    by_id = {t.id: t for t in tools}
    verified: list[tuple[str, str]] = []
    audit: list[dict] = []
    asked: set[tuple[str, str]] = set()

    for rec in gold_trace:
        tool_id = str(rec.get("tool", ""))
        if "::" not in tool_id:
            continue
        a = by_id.get(tool_id)
        if a is None:
            continue
        call = (f"{a.name}({json.dumps(rec.get('args') or {})}) -> "
                f"{str(rec.get('response', ''))[:160]}")

        for b in tools:
            if b.id == a.id:
                continue
            if not cross_server and b.server != a.server:
                continue
            if scope(a.name) != scope(b.name) or _opposed(a.name, b.name):
                continue
            same_stem = stem(a.name) == stem(b.name)
            same_shape = bool(a.args) and a.args == b.args and \
                _description_overlap(a, b) >= 0.25
            if not (same_stem or same_shape):
                continue

            key = tuple(sorted((a.id, b.id)))
            if key in asked:
                continue
            asked.add(key)

            ok, why = verify_pair(a, b, call, ask)
            audit.append({"step_tool": a.id, "alternative": b.id,
                          "satisfies": ok, "why": why, "call": call[:160]})
            if on_result:
                on_result(a, b, ok, why)
            if ok:
                verified.append((a.id, b.id))

    return group(verified), audit


# --------------------------------------------------------------------------
# 3. grouping
# --------------------------------------------------------------------------

class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def group(verified: Iterable[tuple[str, str]]) -> EFSIndex:
    """Verified pairs -> connected components.

    Transitivity is the point: if A~B and B~C then a model answering C is
    correct for a node whose gold is A.
    """
    uf = _UnionFind()
    for a, b in verified:
        uf.union(a, b)
    buckets: dict[str, set[str]] = {}
    for t in list(uf.parent):
        buckets.setdefault(uf.find(t), set()).add(t)
    return EFSIndex(sets=[s for s in buckets.values() if len(s) > 1])


# --------------------------------------------------------------------------
# 4. plan expansion  -- what the scorer consumes
# --------------------------------------------------------------------------

def expand_plan(plan: Sequence[Sequence[dict]], index: EFSIndex) -> list[list[dict]]:
    """Widen every gold node to its equivalence set.

    A node authored as one tool becomes the set of tools that satisfy it, which
    is what GraphEvaluator matches against.
    """
    out: list[list[dict]] = []
    for step in plan:
        seen: set[str] = set()
        widened: list[dict] = []
        for alt in step:
            server = alt.get("server_name") or alt.get("server") or ""
            name = alt.get("tool_name") or alt.get("tool") or ""
            for eq in sorted(index.equivalents(f"{server}::{name}")):
                if eq in seen:
                    continue
                seen.add(eq)
                s, _, n = eq.partition("::")
                widened.append({**alt, "server_name": s, "tool_name": n})
        out.append(widened or list(step))
    return out


def coverage(plan: Sequence[Sequence[dict]], index: EFSIndex) -> dict[str, Any]:
    """Gate 6: is every gold node's equivalence set resolved?

    A node with no entry has not been checked -- which is different from a node
    checked and found unique. Reporting them separately keeps 'not yet audited'
    from masquerading as 'verified unique'.
    """
    nodes, resolved = [], 0
    for i, step in enumerate(plan):
        for alt in step:
            server = alt.get("server_name") or alt.get("server") or ""
            name = alt.get("tool_name") or alt.get("tool") or ""
            tid = f"{server}::{name}"
            has = tid in index._lookup
            resolved += has
            nodes.append({"step": i, "tool": tid, "resolved": has,
                          "alternatives": len(index.equivalents(tid))})
            break  # one representative per step is enough for the gate
    return {
        "nodes": len(nodes),
        "resolved": resolved,
        "unresolved": [n["tool"] for n in nodes if not n["resolved"]],
        "fully_covered": resolved == len(nodes),
        "detail": nodes,
    }
