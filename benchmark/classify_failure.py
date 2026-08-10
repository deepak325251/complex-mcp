from __future__ import annotations

import json
from typing import Any, Iterable

from benchmark.failure_taxonomy import FailureClass, FailureVerdict


def _lower(text: str | None) -> str:
    return (text or "").lower()


def _tool_names_from_trajectory(trajectory: dict[str, Any] | list[dict]) -> list[str]:
    steps = trajectory.get("steps") if isinstance(trajectory, dict) else trajectory
    if not steps:
        return []
    names: list[str] = []
    for step in steps:
        name = step.get("tool")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _has_error_status(step: dict) -> bool:
    resp = step.get("response")
    if not isinstance(resp, dict):
        return False
    status = str(resp.get("status", "")).lower()
    return status in {"error", "failed", "internel error", "internal error"}


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
        return FailureVerdict(FailureClass.UNKNOWN,
                              "task passed; no failure to classify",
                              {"passed": True})

    tool_cnt: dict[str, dict[str, int]] = tool_summary.get("tool_cnt") or {}
    ep_valid = int(tool_summary.get("valid_tool_calls") or 0)
    ep_invalid = int(tool_summary.get("invalid_tool_calls") or 0)
    ep_error = int(tool_summary.get("error_tool_calls") or 0)

    tool_names_called = _tool_names_from_trajectory(trajectory)
    expected_tools = task_context.get("expected_tools") or []
    stump_levers = task_context.get("stump_levers") or []

    recall = score.get("recall") or 0
    total = score.get("total") or 0
    misbehave = score.get("misbehave") or 0

    if max_turns_hit:
        return FailureVerdict(
            FailureClass.MAX_TURNS_EXCEEDED,
            "agent ran out of turns without producing [END]",
            {"max_turns_hit": True, "valid_calls": ep_valid},
        )

    if ep_valid == 0 and ep_invalid == 0 and ep_error == 0:
        if final_message and len(final_message.strip()) > 40:
            return FailureVerdict(
                FailureClass.REFUSED,
                "no tool calls attempted; agent produced text-only response (length > 40 chars)",
                {"final_msg_len": len(final_message.strip())},
            )
        return FailureVerdict(
            FailureClass.NO_TOOL_CALLS,
            "no tool calls attempted and no substantive output",
            {"final_msg_len": len(final_message.strip()) if final_message else 0},
        )

    if ep_valid == 0 and ep_invalid > 0:
        return FailureVerdict(
            FailureClass.FORMAT_ERROR,
            f"all {ep_invalid} tool attempts were unparseable or unknown",
            {"invalid_calls": ep_invalid},
        )

    if expected_tools:
        expected_set = set(expected_tools)
        called_set = set(tool_names_called)
        wrong_tools = called_set - expected_set - {"login", "logout"}
        if wrong_tools and not (called_set & expected_set):
            return FailureVerdict(
                FailureClass.WRONG_TOOL,
                f"none of {len(called_set)} unique called tools match expected set",
                {"called": sorted(called_set), "expected": sorted(expected_set)},
            )

    prereq_pairs = [
        ("wait_payment_password", "checkout_all"),
    ]
    for prereq, action in prereq_pairs:
        if action in expected_tools and action in tool_names_called and prereq not in tool_names_called:
            return FailureVerdict(
                FailureClass.MISSING_PREREQ,
                f"called {action} without required prerequisite {prereq}",
                {"prereq": prereq, "action": action},
            )

    if "dirty_state" in stump_levers and total > 0 and recall < total and misbehave == 0:
        cleanup_hints = {"delete", "remove", "clear", "unlike", "unstar", "mark_as_read", "unblock", "cancel"}
        touched_cleanup = any(any(h in name.lower() for h in cleanup_hints) for name in tool_names_called)
        if not touched_cleanup:
            return FailureVerdict(
                FailureClass.DIRTY_STATE_IGNORED,
                "task is a dirty_state task but agent called no cleanup-style tools",
                {"called": tool_names_called},
            )

    steps = trajectory.get("steps") if isinstance(trajectory, dict) else trajectory
    error_steps = [s for s in (steps or []) if _has_error_status(s)]
    if len(error_steps) >= 3 and (recall == 0 or (total and recall / total < 0.5)):
        return FailureVerdict(
            FailureClass.TOOL_ERROR_UNRECOVERED,
            f"agent hit {len(error_steps)} tool errors and did not recover",
            {"error_steps": len(error_steps)},
        )

    if ep_valid >= 2 and total > 0 and 0 < recall < total:
        return FailureVerdict(
            FailureClass.PARTIAL_COMPLETION,
            f"partial state changes: recall {recall}/{total}",
            {"recall": recall, "total": total, "valid_calls": ep_valid},
        )

    return FailureVerdict(
        FailureClass.UNKNOWN,
        "no rule matched; inspect trajectory manually",
        {
            "valid_calls": ep_valid,
            "invalid_calls": ep_invalid,
            "error_calls": ep_error,
            "recall": recall,
            "total": total,
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
