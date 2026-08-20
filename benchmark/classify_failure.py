from __future__ import annotations

import json
from typing import Any, Iterable, Sequence

from benchmark.failure_taxonomy import (
    FailureClass,
    FailureVerdict,
    LEVER_TO_EXPECTED_MODES,
    MODE_TO_CATEGORY,
)


GATE_SIGNATURES: dict[str, str] = {
    "please enter the trading password": "wait_trade_password",
    "please enter the payment password": "wait_payment_password",
    "this operation need privilege": "ask_for_privilege",
    "vip only": "upgrade_to_vip",
    "has not been logged into yet": "login",
    "not logged in": "login",
}


TRANSIENT_SIGNATURES: tuple[str, ...] = (
    "network issue",
    "internel error",
    "internal error",
    "please try again",
    "timed out",
    "timeout",
    "connection reset",
)


READ_PREFIXES: tuple[str, ...] = (
    "get_", "list_", "check_", "search_", "fuzzy_search_", "read_", "fetch_",
    "browse_", "view_", "show_",
)


# Server-side exceptions: the tool IMPLEMENTATION crashed (a harness/world defect),
# not an app-level rejection the agent could have avoided. Never blame the model.
INFRA_ERROR_SIGNATURES: tuple[str, ...] = (
    "error calling tool",
    "traceback (most recent call",
    "list index out of range",
    "object has no attribute",
    "list indices must be integers",
    "'nonetype' object",
    "keyerror", "attributeerror", "indexerror", "typeerror", "valueerror",
    "unhashable type", "not json serializable",
)


# App-level "the thing you named does not exist". When the agent supplies an id
# that no prior read ever surfaced, that rejection means an invented (hallucinated)
# argument, not a real dirty-state / missing-prereq problem.
NOT_FOUND_SIGNATURES: tuple[str, ...] = (
    "not found", "does not exist", "doesn't exist", "no such",
    "unknown id", "invalid id", "could not find",
)

_ID_ARG_HINTS: frozenset[str] = frozenset({
    "id", "sid", "tid", "uid", "cid", "gid", "mid", "aid", "oid",
    "bid", "rid", "pid", "eid", "event_id", "channel", "org_id",
})


UTILITY_TOOLS: frozenset[str] = frozenset({
    "acc_network", "change_my_ip", "list_ip_choices",
    "wait_trade_password", "wait_payment_password", "ask_for_privilege",
    "upgrade_to_vip", "now", "health", "login", "logout",
})


CLEANUP_HINTS: frozenset[str] = frozenset({
    "delete", "remove", "clear", "unlike", "unstar", "mark_as_read",
    "unblock", "cancel", "unfollow", "unsubscribe", "empty", "purge",
})


def _base(name: str | None) -> str:
    """Strip 'Server::' prefix from qualified tool names to compare bare names."""
    if not name:
        return ""
    if "::" in name:
        return name.rsplit("::", 1)[-1]
    return name


def _lower(text: str | None) -> str:
    return (text or "").lower()


def _resp_body(step: dict) -> str:
    resp = step.get("response")
    if isinstance(resp, dict):
        try:
            return json.dumps(resp).lower()
        except (TypeError, ValueError):
            return str(resp).lower()
    return str(resp or "").lower()


def _has_error_status(step: dict) -> bool:
    resp = step.get("response")
    if not isinstance(resp, dict):
        return False
    status = str(resp.get("status", "")).lower()
    return status in {"error", "failed", "internel error", "internal error"}


def _is_read(name: str | None) -> bool:
    base = _base(name)
    return any(base.startswith(p) for p in READ_PREFIXES)


def _is_utility(name: str | None) -> bool:
    return _base(name) in UTILITY_TOOLS


def _steps(trajectory: dict[str, Any] | list[dict] | None) -> list[dict]:
    if not trajectory:
        return []
    if isinstance(trajectory, dict):
        return trajectory.get("steps") or []
    return list(trajectory)


def _tool_names(trajectory: dict[str, Any] | list[dict] | None) -> list[str]:
    return [_base(s.get("tool")) for s in _steps(trajectory) if s.get("tool")]


def _first_write_index(steps: Sequence[dict]) -> int | None:
    for i, s in enumerate(steps):
        name = s.get("tool")
        if not name:
            continue
        if _is_read(name) or _is_utility(name):
            continue
        return i
    return None


def _crux_aligned(mode: FailureClass, levers: Iterable[str]) -> bool | None:
    levers = list(levers or [])
    if not levers:
        return None
    for lever in levers:
        expected = LEVER_TO_EXPECTED_MODES.get(lever, set())
        if mode.value in expected:
            return True
    return False


def _detect_gate_prerequisite(
    steps: Sequence[dict],
) -> tuple[str, dict] | None:
    for i, step in enumerate(steps):
        body = _resp_body(step)
        for signature, opener in GATE_SIGNATURES.items():
            if signature not in body:
                continue
            tail = steps[i + 1:]
            if any(_base(t.get("tool")) == opener for t in tail):
                continue
            return (
                opener,
                {"step": i, "gate": signature, "tool": _base(step.get("tool"))},
            )
    return None


def _detect_transient_defeatism(
    steps: Sequence[dict],
) -> dict | None:
    for i in range(len(steps) - 1, -1, -1):
        step = steps[i]
        body = _resp_body(step)
        if not any(sig in body for sig in TRANSIENT_SIGNATURES):
            continue
        this_tool = _base(step.get("tool"))
        tail = steps[i + 1:]
        retried = any(_base(t.get("tool")) == this_tool for t in tail)
        recovered = any(_base(t.get("tool")) in {"acc_network", "change_my_ip"} for t in tail)
        progressed = any(
            not _has_error_status(t) and not _is_read(t.get("tool")) and not _is_utility(t.get("tool"))
            for t in tail
        )
        if not retried and not recovered and not progressed and len(tail) <= 2:
            return {"step": i, "tool": this_tool, "body": body[:160]}
    return None


def _read_response_is_empty(step: dict) -> bool:
    resp = step.get("response")
    if isinstance(resp, dict):
        out = resp.get("output")
        if out is None:
            return True
        if isinstance(out, (list, dict)):
            return len(out) == 0
        if isinstance(out, str):
            return out.strip() == ""
        return False
    return not resp


def _no_dirty_state_evidence(steps: Sequence[dict]) -> bool:
    """True when every listing-style call (``list_*``) the agent made came
    back empty -- i.e. the world never actually surfaced a collection for
    the dirty_state lever to act on, so the agent can't be faulted for not
    cleaning it up. Only fires when there's at least one such call; agents
    that never looked at all still get DIRTY_STATE_IGNORED as before.
    """
    list_steps = [s for s in steps if _base(s.get("tool")).startswith("list_")]
    if not list_steps:
        return False
    return all(_read_response_is_empty(s) for s in list_steps)


def _is_infra_error(step: dict) -> bool:
    """A server-side crash inside the tool (harness/world defect), as opposed to
    a normal app-level rejection ('X not found'). Only the former should be
    attributed to infrastructure rather than the agent."""
    if not _has_error_status(step):
        return False
    body = _resp_body(step).lower()
    return any(sig in body for sig in INFRA_ERROR_SIGNATURES)


def _is_id_key(k: str) -> bool:
    k = str(k or "").lower()
    return (k == "id" or k == "slug" or k.endswith("_id") or k.endswith("_slug")
            or k in _ID_ARG_HINTS)


def _looks_like_id(key: str, val: Any) -> bool:
    return _is_id_key(key) and isinstance(val, str) and len(val) >= 3


def _harvest_ids(resp: Any) -> set[str]:
    """Every id/slug-shaped string value appearing anywhere in a tool response --
    the pool of entity handles the agent legitimately learned about."""
    found: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and _is_id_key(k):
                    found.add(v)
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(resp)
    return found


def _detect_hallucinated_arg(steps: Sequence[dict]) -> dict | None:
    """The agent called a tool with an entity id that no PRIOR response ever
    surfaced, and the tool rejected it as non-existent -> invented argument."""
    seen: set[str] = set()
    for i, s in enumerate(steps):
        if _has_error_status(s):
            body = _resp_body(s).lower()
            if any(sig in body for sig in NOT_FOUND_SIGNATURES):
                for k, v in (s.get("arguments") or {}).items():
                    if _looks_like_id(k, v) and v not in seen:
                        return {"step": i, "tool": _base(s.get("tool")),
                                "arg": k, "value": v}
        seen |= _harvest_ids(s.get("response"))
    return None


def classify(
    *,
    trajectory: dict[str, Any] | list[dict] | None,
    tool_summary: dict[str, Any] | None,
    score: dict[str, Any] | None,
    task_context: dict[str, Any] | None = None,
    final_message: str | None = None,
    max_turns_hit: bool = False,
) -> FailureVerdict:
    trajectory = trajectory or {"steps": []}
    tool_summary = tool_summary or {}
    score = score or {}
    task_context = task_context or {}

    if score.get("passed") is True:
        return FailureVerdict(
            FailureClass.UNKNOWN,
            "task passed; no failure to classify",
            {"passed": True},
        )

    ep_valid = int(tool_summary.get("valid_tool_calls") or 0)
    ep_invalid = int(tool_summary.get("invalid_tool_calls") or 0)
    ep_error = int(tool_summary.get("error_tool_calls") or 0)

    steps = _steps(trajectory)
    tool_names_called = _tool_names(trajectory)
    expected_tools = task_context.get("expected_tools") or []
    stump_levers = task_context.get("stump_levers") or []

    recall = int(score.get("recall") or 0)
    total = int(score.get("total") or 0)
    misbehave = int(score.get("misbehave") or 0)

    # recall/total/misbehave only mean COMPLETION / state-damage when they came
    # from a live state or traj channel. If the state channel was inadmissible
    # (e.g. an empty facade dump) the aggregate falls back to plan nodes
    # (misbehave_kind == "plan_fp") -- calling those "partial state changes" or
    # "damaged protected state" would be a lie. state_metrics gates that.
    misbehave_kind = score.get("misbehave_kind")
    state_admissible = score.get("state_admissible")
    state_metrics = (state_admissible is not False
                     and misbehave_kind in (None, "state_guard", "traj_guard"))

    def _verdict(fc: FailureClass, reason: str, evidence: dict) -> FailureVerdict:
        aligned = _crux_aligned(fc, stump_levers)
        if aligned is not None:
            evidence = {**evidence, "crux_aligned": aligned, "stump_levers": list(stump_levers)}
        return FailureVerdict(fc, reason, evidence)

    # An unmeasurable state channel is a HARNESS fact, not a model behaviour.
    # These runs previously came back `partial_completion` / `unknown`, which
    # sent environment defects to the model-behaviour pile in every failure
    # histogram. Decided before any behavioural rule so nothing can outrank it.
    if state_admissible is False:
        return _verdict(
            FailureClass.ENVIRONMENT_MISMATCH,
            f"state channel not gradeable ({score.get('state_reason') or 'inadmissible'}); "
            f"no conclusion about the agent can be drawn from it",
            {"state_admissible": False, "state_reason": score.get("state_reason"),
             "misbehave_kind": misbehave_kind})

    if max_turns_hit:
        return _verdict(
            FailureClass.MAX_TURNS_EXCEEDED,
            "agent ran out of turns without producing [END]",
            {"max_turns_hit": True, "valid_calls": ep_valid},
        )

    if ep_valid == 0 and ep_invalid == 0 and ep_error == 0:
        if final_message and len(final_message.strip()) > 40:
            return _verdict(
                FailureClass.REFUSED,
                "no tool calls attempted; agent produced text-only response (length > 40 chars)",
                {"final_msg_len": len(final_message.strip())},
            )
        return _verdict(
            FailureClass.NO_TOOL_CALLS,
            "no tool calls attempted and no substantive output",
            {"final_msg_len": len(final_message.strip()) if final_message else 0},
        )

    if ep_valid == 0 and ep_invalid > 0:
        return _verdict(
            FailureClass.FORMAT_ERROR,
            f"all {ep_invalid} tool attempts were unparseable or unknown",
            {"invalid_calls": ep_invalid},
        )

    gate = _detect_gate_prerequisite(steps)
    if gate is not None:
        opener, ev = gate
        return _verdict(
            FailureClass.MISSING_PREREQ,
            f"gate rejected at step {ev['step']} on {ev['tool']}; never called '{opener}' to open it",
            {**ev, "opener": opener},
        )

    if expected_tools:
        expected_set = {_base(t) for t in expected_tools}
        called_set = set(tool_names_called)
        wrong_tools = called_set - expected_set - {"login", "logout"} - UTILITY_TOOLS
        if wrong_tools and not (called_set & expected_set):
            distraction = "distractor_saturation" in (stump_levers or [])
            fc = FailureClass.DISTRACTION_DERAILED if distraction else FailureClass.WRONG_TOOL
            return _verdict(
                fc,
                f"none of {len(called_set)} unique called tools match expected set",
                {"called": sorted(called_set), "expected": sorted(expected_set)},
            )

    defeat = _detect_transient_defeatism(steps)
    if defeat is not None:
        return _verdict(
            FailureClass.ERR_RECOVERY,
            f"hit recoverable error on {defeat['tool']} at step {defeat['step']} and stopped without retrying or invoking a recovery tool",
            defeat,
        )

    error_steps = [s for s in steps if _has_error_status(s)]
    _halluc = _detect_hallucinated_arg(steps)
    if len(error_steps) >= 3 and (recall == 0 or (total and recall / total < 0.5)):
        infra_steps = [s for s in error_steps if _is_infra_error(s)]
        # Server-side crashes (KeyError/AttributeError/"Error calling tool") are a
        # HARNESS/world defect, not the agent failing to recover -- split them out
        # so the model isn't blamed for a broken tool implementation.
        if len(infra_steps) * 2 >= len(error_steps):
            return _verdict(
                FailureClass.INFRA_ERROR,
                f"{len(infra_steps)}/{len(error_steps)} tool errors are server-side "
                f"crashes (harness/world defect, not the agent)",
                {"infra_steps": len(infra_steps), "error_steps": len(error_steps)},
            )
        # Many errors all from named-but-nonexistent entities -> the agent was
        # inventing ids/slugs (hallucination), not just "failing to recover".
        halluc_errs = [s for s in error_steps
                       if any(sig in _resp_body(s).lower() for sig in NOT_FOUND_SIGNATURES)]
        if _halluc is not None and len(halluc_errs) * 2 >= len(error_steps):
            return _verdict(
                FailureClass.HALLUCINATED_ARG,
                f"{len(halluc_errs)}/{len(error_steps)} errors are invented entity "
                f"ids/slugs the agent never read (e.g. {_halluc['arg']}='{_halluc['value']}')",
                {**_halluc, "halluc_errors": len(halluc_errs), "error_steps": len(error_steps)},
            )
        return _verdict(
            FailureClass.TOOL_ERROR_UNRECOVERED,
            f"agent hit {len(error_steps)} tool errors and did not recover",
            {"error_steps": len(error_steps), "infra_steps": len(infra_steps)},
        )

    # A single invented-id rejection (below the multi-error threshold above).
    if _halluc is not None:
        return _verdict(
            FailureClass.HALLUCINATED_ARG,
            f"called {_halluc['tool']} with {_halluc['arg']}='{_halluc['value']}' "
            f"which no prior read surfaced -- invented (hallucinated) argument",
            _halluc,
        )

    if state_metrics and misbehave > 0 and total > 0 and recall >= max(1, total // 2):
        return _verdict(
            FailureClass.OVER_ACTION,
            f"reached partial goal (recall {recall}/{total}) but damaged {misbehave} protected state field(s)",
            {"recall": recall, "total": total, "misbehave": misbehave},
        )

    if "dirty_state" in stump_levers and total > 0 and recall < total and misbehave == 0:
        touched_cleanup = any(
            any(h in name.lower() for h in CLEANUP_HINTS) for name in tool_names_called
        )
        if not touched_cleanup:
            if _no_dirty_state_evidence(steps):
                return _verdict(
                    FailureClass.ENVIRONMENT_MISMATCH,
                    "dirty_state lever declared but every list_-style call the agent made "
                    "came back empty; the runtime never surfaced a dirty collection to clean",
                    {"called": tool_names_called},
                )
            return _verdict(
                FailureClass.DIRTY_STATE_IGNORED,
                "dirty_state lever active but agent called no cleanup-style tools",
                {"called": tool_names_called},
            )

    first_write = _first_write_index(steps)
    if (state_metrics and first_write is not None and first_write == 0
            and total > 0 and misbehave > 0):
        return _verdict(
            FailureClass.CLEAN_SLATE_BIAS,
            f"agent's first action was a write ({_base(steps[0].get('tool'))}) with no prior state read",
            {"first_tool": _base(steps[0].get("tool")), "misbehave": misbehave},
        )

    if ep_valid >= 2 and total > 0 and 0 < recall < total:
        # Honest wording: only call it a STATE change when the numbers are state
        # metrics; otherwise it is partial plan coverage with the state channel
        # unavailable, and the reason/evidence must say so (fixes the "partial
        # state changes" mislabel on an empty-dump run).
        if state_metrics:
            reason = f"partial state changes: recall {recall}/{total}"
            ev = {"recall": recall, "total": total, "valid_calls": ep_valid}
        else:
            reason = (f"partial plan coverage: recall {recall}/{total} "
                      f"(state channel unavailable: "
                      f"{score.get('state_reason') or 'inadmissible'})")
            ev = {"recall": recall, "total": total, "valid_calls": ep_valid,
                  "state_admissible": False,
                  "state_reason": score.get("state_reason")}
        return _verdict(FailureClass.PARTIAL_COMPLETION, reason, ev)

    if total > 0 and recall >= total and misbehave == 0:
        return _verdict(
            FailureClass.EXECUTION_DROP,
            f"reached all gold nodes (recall {recall}/{total}) with no misbehavior "
            f"but state transitions did not verify -- a planned action likely "
            f"slipped between reasoning and the tool trace",
            {"recall": recall, "total": total, "misbehave": misbehave},
        )

    return _verdict(
        FailureClass.UNKNOWN,
        "no rule matched; inspect trajectory manually",
        {
            "valid_calls": ep_valid,
            "invalid_calls": ep_invalid,
            "error_calls": ep_error,
            "recall": recall,
            "total": total,
            "misbehave": misbehave,
        },
    )


def parse_expected_tools(expected_tool_calls_field: str | dict | None) -> list[str]:
    if not expected_tool_calls_field:
        return []
    if isinstance(expected_tool_calls_field, dict):
        return list(expected_tool_calls_field.keys())
    try:
        parsed = json.loads(expected_tool_calls_field)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(parsed, dict):
        return list(parsed.keys())
    return []
