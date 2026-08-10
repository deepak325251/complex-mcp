"""Deterministic failure-mode classification.

Input: the environment trace (what the sandbox did), the ATIF trajectory (what
the agent saw and said), the judge result, and the gold plan.
Output: a labelled primary failure mode plus supporting evidence.

Every rule here is mechanical. No LLM call is required for the eight modes in
taxonomy.DETERMINISTIC_MODES, which covers all four stateful modes -- the ones
this corpus exists to provoke. An LLM second opinion is optional and only used
for the cognitive modes, where intent genuinely has to be read.

This labelling is what makes the data worth training on: a client gets a reason
for every negative, not just a reward of 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .taxonomy import LEVER_TO_EXPECTED_MODES, MODE_TO_CATEGORY

# INVARIANT: the facade records tool names in QUALIFIED form ("LightStock::
# place_market_order") because that is what it dispatches on. Every detector
# below compares against BARE names, so all comparisons must go through
# _base(). Comparing rec["tool"] directly silently never matches -- which
# reads as "the model never called the recovery tool" and fabricates a
# failure mode.

# Substrings the sandbox emits when a gate blocks an action. Extending the
# sandbox means extending this map.
GATE_SIGNATURES: dict[str, str] = {
    "please enter the trading password": "wait_trade_password",
    "please enter the payment password": "wait_payment_password",
    "this operation need privilege": "ask_for_privilege",
    "vip": "upgrade_to_vip",
    "has not been logged into yet": "login",
}

# Substrings that mark a *recoverable* environment error.
TRANSIENT_SIGNATURES: tuple[str, ...] = (
    "network issue",
    "internel error",   # sic -- sandbox spelling
    "internal error",
    "please try again",
    "timed out",
)

# Tools that read state without mutating it. Used to detect verify-before-act.
READ_PREFIXES: tuple[str, ...] = (
    "get_", "list_", "check_", "search_", "fuzzy_search_", "read_", "fetch_",
)

# Neither reads nor state mutations: session plumbing the agent must perform to
# proceed. Counting these as "writes" makes a recovery call look like acting
# blind on state it never inspected.
UTILITY_TOOLS: frozenset[str] = frozenset({
    "acc_network", "change_my_ip", "list_ip_choices",
    "wait_trade_password", "wait_payment_password", "ask_for_privilege",
    "upgrade_to_vip", "now", "health",
})


@dataclass
class Evidence:
    step: int
    detail: str

    def as_dict(self) -> dict:
        return {"step": self.step, "detail": self.detail}


@dataclass
class Diagnosis:
    primary_mode: str
    category: str
    explanation: str
    all_modes: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    deterministic: bool = True
    crux_aligned: bool | None = None   # did it fail for the advertised reason?

    def as_dict(self) -> dict:
        return {
            "primary_failure": {
                "mode": self.primary_mode,
                "category": self.category,
                "explanation": self.explanation,
            },
            "all_modes": self.all_modes,
            "evidence": [e.as_dict() for e in self.evidence],
            "deterministic": self.deterministic,
            "crux_aligned": self.crux_aligned,
        }


def classify(
    *,
    trace: Sequence[dict],
    judge_result: dict,
    gold_trace: Sequence[dict] | None = None,
    levers: Sequence[str] = (),
    timed_out: bool = False,
    infra_error: str | None = None,
    final_message: str = "",
    efs=None,
) -> Diagnosis:
    """Label a single run.

    Rules are ordered by specificity: the most diagnostic signal wins. A run
    that both gave up on a transient error *and* left the cart dirty is
    primarily an err_recovery failure, because that is what stopped it.
    """
    if infra_error:
        return Diagnosis("infra_error", "programmatic", infra_error, deterministic=True)

    passed = judge_result.get("passed", False)
    if passed:
        return Diagnosis("solved", "programmatic", "Rc == 1 and Rb == 0.", deterministic=True)

    hits: list[tuple[str, str, list[Evidence]]] = []

    # --- no tool use ------------------------------------------------------
    if not trace:
        hits.append(("no_tool_use", "Agent produced no tool calls at all.", []))

    # --- malformed calls ---------------------------------------------------
    malformed = [i for i, r in enumerate(trace) if r.get("status") == "malformed"]
    if malformed:
        hits.append((
            "malformed_call",
            f"{len(malformed)} call(s) were rejected before reaching a server "
            f"(bad schema or hallucinated tool name).",
            [Evidence(i, f"{trace[i].get('tool')}: {trace[i].get('response', '')[:120]}")
             for i in malformed[:5]],
        ))

    # --- strategic defeatism ----------------------------------------------
    defeat = _detect_defeatism(trace)
    if defeat:
        hits.append(defeat)

    # --- missing prerequisite ---------------------------------------------
    prereq = _detect_missing_prerequisite(trace)
    if prereq:
        hits.append(prereq)

    # --- clean-slate bias --------------------------------------------------
    if gold_trace:
        clean = _detect_clean_slate(trace, gold_trace)
        if clean:
            hits.append(clean)

    # --- referential error -------------------------------------------------
    if gold_trace:
        ref = _detect_referential(trace, gold_trace, efs)
        if ref:
            hits.append(ref)

    # --- an operation the gold run committed and this one never did --------
    if gold_trace:
        skipped = _detect_missing_gold_tool(trace, gold_trace, final_message, efs)
        if skipped:
            hits.append(skipped)

    # --- over-action -------------------------------------------------------
    damaged = judge_result.get("damaged_negative", [])
    if damaged:
        paths = ", ".join(".".join(str(p) for p in d["path"]) for d in damaged[:4])
        hits.append((
            "over_action",
            f"Rb > 0: {len(damaged)} state key(s) changed that should not have. {paths}",
            [],
        ))

    # --- early termination -------------------------------------------------
    if timed_out:
        hits.append(("early_termination", "Agent hit the wall-clock timeout.", []))
    elif gold_trace and len(trace) < 0.5 * len(gold_trace) and judge_result.get("recall", 0) < judge_result.get("total", 1):
        hits.append((
            "early_termination",
            f"Agent stopped after {len(trace)} calls; gold needed {len(gold_trace)}. "
            f"Rc = {judge_result.get('completion_rate', 0):.2f}.",
            [],
        ))

    if not hits:
        return Diagnosis(
            "faulty_synthesis",
            MODE_TO_CATEGORY.get("faulty_synthesis", "cognitive"),
            "Ran a plausible plan but the end state is wrong; no mechanical signal "
            "isolates the cause. Needs an LLM second opinion or human review.",
            deterministic=False,
        )

    primary, why, ev = hits[0]
    all_modes = [h[0] for h in hits]
    return Diagnosis(
        primary_mode=primary,
        category=MODE_TO_CATEGORY.get(primary, "unknown"),
        explanation=why,
        all_modes=all_modes,
        evidence=ev,
        deterministic=True,
        crux_aligned=_crux_aligned(all_modes, levers),
    )


# --------------------------------------------------------------------------
# Individual detectors
# --------------------------------------------------------------------------

def _detect_defeatism(trace: Sequence[dict]) -> tuple[str, str, list[Evidence]] | None:
    """Transient error near the end, no retry, no recovery tool.

    This is the GPT-5.1 pattern from the ComplexMCP paper: hit a recoverable
    network error, explain politely that it could not continue, stop.
    """
    for i in range(len(trace) - 1, -1, -1):
        rec = trace[i]
        body = str(rec.get("response", "")).lower()
        if not any(sig in body for sig in TRANSIENT_SIGNATURES):
            continue

        tail = trace[i + 1:]
        retried = any(_base(t) == _base(rec) for t in tail)
        recovered = any(_base(t) in {"acc_network", "change_my_ip"} for t in tail)
        # Completing a mutation after the error IS recovery, whatever route it
        # took. Without this the rule fires on the last transient error of any
        # run that hit one -- even a run that shrugged it off and finished the
        # job -- which mislabels the failure and hides the real cause.
        progressed = any(
            t.get("status") == "ok" and not _is_read(t) for t in tail
        )
        if not retried and not recovered and not progressed and len(tail) <= 2:
            return (
                "err_recovery",
                f"Hit a recoverable error on {rec.get('tool')} at step {i} and stopped "
                f"after {len(tail)} further call(s) without retrying or invoking a "
                f"recovery tool.",
                [Evidence(i, str(rec.get("response", ""))[:160])],
            )
    return None


def _detect_missing_prerequisite(trace: Sequence[dict]) -> tuple[str, str, list[Evidence]] | None:
    """Gate rejection with no subsequent call to the gate-opening tool."""
    for i, rec in enumerate(trace):
        body = str(rec.get("response", "")).lower()
        for signature, opener in GATE_SIGNATURES.items():
            if signature not in body:
                continue
            if any(_base(t) == opener for t in trace[i + 1:]):
                continue  # recovered correctly
            return (
                "missing_prerequisite",
                f"Blocked at step {i} by a gate on {rec.get('tool')} and never called "
                f"'{opener}' to open it.",
                [Evidence(i, str(rec.get("response", ""))[:160])],
            )
    return None


def _detect_clean_slate(
    trace: Sequence[dict], gold_trace: Sequence[dict]
) -> tuple[str, str, list[Evidence]] | None:
    """Gold verifies before its first write; the model writes blind."""
    gold_first_write = _first_write_index(gold_trace)
    if gold_first_write is None:
        return None
    gold_reads_first = any(_is_read(t) for t in gold_trace[:gold_first_write])
    if not gold_reads_first:
        return None  # task does not require verify-before-act

    model_first_write = _first_write_index(trace)
    if model_first_write is None:
        return None

    write = trace[model_first_write]

    # The question is not "did it read anything" but "did it read the same
    # thing gold read before writing". A model that consults a catalogue and
    # then mutates a cart it never inspected has still acted blind.
    gold_checks = {
        _base(t) for t in gold_trace[:gold_first_write] if _is_read(t)
    }
    model_checks = {
        _base(t) for t in trace[:model_first_write]
        if _is_read(t) and t.get("status") == "ok"
    }
    if gold_checks & model_checks:
        return None  # performed the same verification gold did

    return (
        "clean_slate_bias",
        f"Wrote to the environment at step {write.get('i', model_first_write)} "
        f"({_base(write)}) without first reading the state it was mutating. "
        f"The gold trajectory reads before writing.",
        [Evidence(write.get("i", model_first_write), f"first write: {_base(write)}")],
    )


# Tools whose successful output IS an entity identifier.
IDENTITY_TOOLS = {"get_myuid", "get_my_name", "get_uid_from_name",
                  "fuzzy_search_uids_from_name", "check_passengers"}


# Tools whose success COMMITS work. Calling the setup and skipping these leaves
# the task looking done from the inside -- a cart with an item in it, a booking
# never paid for -- while the world says nothing happened.
COMMIT_TOOLS: frozenset[str] = frozenset({
    "checkout_all", "checkout_bookings", "place_market_order", "send_message",
    "send_message_to_group", "cancel_booking", "cancel_order", "post_moment",
})

CLAIM_PHRASES: tuple[str, ...] = (
    "all done", "completed", "successfully", "i've ", "i have ", "purchased",
    "bought", "booked", "sent", "done!",
)


def _equivalents(name: str, efs) -> set[str]:
    """Bare names that satisfy the same step as `name`.

    Comparing gold tools against model tools by NAME reintroduces exactly the
    false negative equal function sets exist to prevent: a model that used
    fuzzy_search_uids_from_name where gold used get_uid_from_name did the same
    job, and must not be reported as having skipped a step.
    """
    if efs is None:
        return {name}
    out = {name}
    for tid in list(efs._lookup):
        if tid.split("::")[-1] == name:
            out |= {e.split("::")[-1] for e in efs.equivalents(tid)}
    return out


def _satisfied(name: str, model_ok: set[str], efs) -> bool:
    return bool(_equivalents(name, efs) & model_ok)


def _detect_missing_gold_tool(
    trace: Sequence[dict], gold_trace: Sequence[dict], final_message: str, efs=None
) -> tuple[str, str, list[Evidence]] | None:
    """The gold run committed something this run never did.

    This is the failure the other detectors structurally cannot see. Every local
    signal looks healthy -- reads happen before writes, gates get answered,
    faults get retried -- because the model executed a correct *prefix*. What it
    omitted was the call that makes the work real.

    When the closing message also claims the work was done, that is a
    hallucinated completion, which is materially worse than stopping early: the
    run reports success for state that does not exist.
    """
    gold_ok = {_base(t) for t in gold_trace if t.get("status") == "ok"}
    model_ok = {_base(t) for t in trace if t.get("status") == "ok"}
    missing = sorted(n for n in gold_ok & COMMIT_TOOLS
                     if not _satisfied(n, model_ok, efs))
    if not missing:
        return None

    claimed = any(p in (final_message or "").lower() for p in CLAIM_PHRASES)
    named = ", ".join(missing)
    last = trace[-1].get("i", len(trace) - 1) if trace else 0

    if claimed:
        return (
            "hallucinated_fact",
            f"Never successfully called {named}, so that work was never committed "
            f"-- yet the closing message reports the task as done. The setup ran "
            f"(the state was staged) but the committing call did not.",
            [Evidence(last, f"missing commit: {named}")],
        )
    return (
        "early_termination",
        f"Stopped without calling {named}; the gold run needed it to commit the "
        f"change. Preceding steps staged the work but nothing finalised it.",
        [Evidence(last, f"missing commit: {named}")],
    )


def _detect_referential(
    trace: Sequence[dict], gold_trace: Sequence[dict], efs=None
) -> tuple[str, str, list[Evidence]] | None:
    """The model acted on the wrong entity.

    Two ways this happens, and the second is the one that hurts:

      never resolved   no identity tool called at all; the entity was assumed
      resolved+ignored the identity WAS looked up and then not used -- the
                       model had the right answer in hand and wrote to
                       something else

    The second form used to be invisible here, so a run that resolved its own
    id and then messaged a contact was attributed to whatever else went wrong
    in the trace.
    """
    if not any(_base(t) in IDENTITY_TOOLS for t in gold_trace):
        return None

    resolved = {
        str(t.get("response", "")).strip()
        for t in trace
        if _base(t) in IDENTITY_TOOLS and t.get("status") == "ok"
    }
    resolved = {r for r in resolved if r and not r.startswith(("[", "{"))}

    writes = [t for t in trace if not _is_read(t) and t.get("status") == "ok"]
    if not writes:
        return None

    if not resolved:
        return (
            "referential_error",
            "Gold resolves the acting identity before mutating state; the model "
            "never called any identity-resolution tool and acted on an assumed "
            "entity.",
            [Evidence(writes[0].get("i", 0),
                      f"first write without identity resolution: {_base(writes[0])}")],
        )

    # An identity was resolved. Did any write actually use it?
    used_any = False
    for w in writes:
        used = {str(v) for v in (w.get("args") or {}).values()}
        if used & resolved:
            used_any = True
            break

    # Partial resolution: gold consulted identity tools this run skipped, so a
    # field gold read from the environment was supplied from somewhere else.
    # Using the id correctly while inventing the name still addresses the wrong
    # entity, and checking only "was any resolved value used" misses it.
    gold_ident = {_base(t) for t in gold_trace if _base(t) in IDENTITY_TOOLS
                  and t.get("status") == "ok"}
    model_ident = {_base(t) for t in trace if _base(t) in IDENTITY_TOOLS
                   and t.get("status") == "ok"}
    skipped_ident = sorted(n for n in gold_ident
                           if not _satisfied(n, model_ident, efs))
    if skipped_ident:
        bad = writes[-1]
        return (
            "referential_error",
            f"Resolved identity only partially: the gold run also called "
            f"{', '.join(skipped_ident)}, so a field it reads from the "
            f"environment was supplied from somewhere else.",
            [Evidence(bad.get("i", 0),
                      f"skipped {', '.join(skipped_ident)}; wrote "
                      f"{_base(bad)}({json.dumps(bad.get('args') or {})[:100]})")],
        )

    if used_any:
        return None

    ident = sorted(resolved)[0]
    bad = writes[-1]
    return (
        "referential_error",
        f"Resolved the acting identity ({ident}) but wrote to a different entity: "
        f"{_base(bad)}({_target(bad)}). The correct value was in hand and unused.",
        [Evidence(bad.get("i", 0), f"{_base(bad)} args={json.dumps(bad.get('args') or {})[:120]}")],
    )


def _base(rec: dict) -> str:
    """Bare tool name -- the facade records the qualified form."""
    return str(rec.get("tool", "")).split("::")[-1]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _is_read(rec: dict) -> bool:
    return _base(rec).startswith(READ_PREFIXES)


def _first_write_index(trace: Sequence[dict]) -> int | None:
    """First call that actually mutates task-relevant state."""
    for i, rec in enumerate(trace):
        if _is_read(rec) or _base(rec) in UTILITY_TOOLS:
            continue
        if rec.get("status") == "ok":
            return i
    return None


def _target(rec: dict) -> str | None:
    """Best-effort entity identity for a call: the first id-ish argument."""
    args = rec.get("args") or {}
    for key in ("uid", "sid", "tid", "gid", "fid", "oid", "nid", "caid", "bid", "ticker"):
        if key in args:
            return f"{key}={args[key]}"
    return None


def _crux_aligned(modes: Iterable[str], levers: Sequence[str]) -> bool | None:
    """Did the model fail for the reason the task advertises?

    Mirrors Harbor's `difficulty_crux` criterion. A task whose failures never
    match its declared levers has unintended difficulty -- it is measuring
    something other than what the author built.

    Keyed on the PRIMARY mode, not on the union of every mode that fired.
    Secondary modes are consequences, not causes, and several are near-tautologies:
    an agent that makes zero tool calls has also, trivially, terminated early. An
    earlier version intersected all_modes, so a zero-call run scored
    crux_aligned=True on the strength of its incidental `early_termination` --
    and two tasks whose real failure was the model asking for confirmation
    before touching anything both reported `crux_alignment_rate: 1.0,
    admissible: true`. The gate exists to catch exactly that, so it has to
    judge the cause.
    """
    mode_list = list(modes)
    if not levers or not mode_list:
        return None
    expected: set[str] = set()
    for lever in levers:
        expected |= LEVER_TO_EXPECTED_MODES.get(lever, set())
    if not expected:
        return None
    return mode_list[0] in expected
