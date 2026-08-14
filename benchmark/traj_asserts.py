"""Trajectory-assertion helpers for Pytest-based (Channel A) grading.

This replaces state-snapshot comparison. Instead of diffing a world dump, the
task's `tests/test_outputs.py` asserts on what the agent ACTUALLY DID -- the tool
calls, their arguments, and their real responses -- which is robust to the
state-export / seeding differences between harnesses (the trajectory is
ground truth about the agent's behaviour; the snapshot is not).

The runner writes the parsed trajectory to a temp file and points
`COMPLEXMCP_TRAJECTORY` at it. A test module does:

    from benchmark.traj_asserts import calls, called_with, ok, never_called, final

    def test_note_pinned():
        assert called_with("create_note", incident_id="PI001",
                           content_contains=["session_store.write", "2.0.3"])

    def test_no_incident_opened():          # a GUARD (negative weight)
        assert never_called("create_incident", "resolve_incident")

Polarity convention (same as the state kit): every assert is phrased
POSITIVELY. "The agent did a bad thing" is a positive assertion that a forbidden
call happened, carrying a NEGATIVE weight in test_weights.json -- so a crashed
agent that does nothing fails that test (contributes 0) and dodges no penalty.
Use `did_call(...)` for that phrasing; use `never_called(...)` for goals that
assert absence.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

_CACHE: dict[str, Any] = {}
# Native mode disambiguates name-collided tools by prefixing the server, e.g.
# "LightSentry_get_issue". Strip that so tests can match on the bare tool name.
_SERVER_PREFIX = re.compile(r"^Light[A-Za-z0-9]+_")


def trajectory() -> dict:
    """The parsed trajectory: {"steps": [...], "final_message": str}."""
    if "traj" not in _CACHE:
        path = os.environ.get("COMPLEXMCP_TRAJECTORY")
        if not path or not os.path.exists(path):
            raise AssertionError(
                "COMPLEXMCP_TRAJECTORY not set / file missing -- the runner must "
                "stage the trajectory before invoking pytest")
        _CACHE["traj"] = json.loads(open(path).read())
    return _CACHE["traj"]


def steps() -> list[dict]:
    return trajectory().get("steps", []) or []


def final() -> str:
    return trajectory().get("final_message", "") or ""


def _base(name: str | None) -> str:
    if not name:
        return ""
    bare = name.split("::")[-1]
    return _SERVER_PREFIX.sub("", bare)


def _status(step: dict) -> str:
    r = step.get("response")
    return str(r.get("status")) if isinstance(r, dict) else ""


def _resp_text(step: dict) -> str:
    r = step.get("response")
    if isinstance(r, (dict, list)):
        return json.dumps(r, ensure_ascii=False)
    return str(r or "")


# --------------------------------------------------------------------------
# Queries a test asserts on
# --------------------------------------------------------------------------

def calls(tool: str) -> list[dict]:
    """All steps that invoked `tool` (bare name)."""
    return [s for s in steps() if _base(s.get("tool")) == tool]


def called(*tools: str) -> bool:
    """Did the agent invoke every one of these tools at least once?"""
    names = {_base(s.get("tool")) for s in steps()}
    return all(t in names for t in tools)


def did_call(*tools: str) -> bool:
    """Positive phrasing for a forbidden call (use with a NEGATIVE weight)."""
    names = {_base(s.get("tool")) for s in steps()}
    return any(t in names for t in tools)


def never_called(*tools: str) -> bool:
    """True iff none of these tools was invoked (goal phrased as absence)."""
    names = {_base(s.get("tool")) for s in steps()}
    return not any(t in names for t in tools)


def ok(tool: str, min_calls: int = 1) -> bool:
    """Did `tool` succeed (status ok) at least `min_calls` times?"""
    return sum(1 for s in calls(tool) if _status(s) == "ok") >= min_calls


def called_with(tool: str, *, args_equal: dict | None = None,
                content_contains: list[str] | str | None = None,
                require_ok: bool = True) -> bool:
    """A call to `tool` matched the given arg constraints.

    args_equal        each key/value must match the call's arguments exactly
    content_contains  every substring must appear in the JSON of the arguments
                      (case-insensitive) -- for asserting the body carried the
                      right fingerprint / count / release across servers
    require_ok        the matching call must have status ok
    """
    subs = ([content_contains] if isinstance(content_contains, str)
            else list(content_contains or []))
    for s in calls(tool):
        if require_ok and _status(s) != "ok":
            continue
        args = s.get("arguments") or {}
        if not isinstance(args, dict):
            continue
        if args_equal and not all(args.get(k) == v for k, v in args_equal.items()):
            continue
        blob = json.dumps(args, ensure_ascii=False).lower()
        if subs and not all(str(x).lower() in blob for x in subs):
            continue
        return True
    return False


def never_called_with(tool: str, *, args_equal: dict | None = None,
                      content_contains: list[str] | str | None = None,
                      require_ok: bool = False) -> bool:
    """Guardrail negation of called_with: True iff NO call to `tool` matched the
    given arg constraints. Defaults to require_ok=False so a *failed* forbidden
    attempt (e.g. an email that erred) still trips the guard — the intent
    ("never target this address/channel") is violated by the attempt itself.
    """
    return not called_with(tool, args_equal=args_equal,
                           content_contains=content_contains,
                           require_ok=require_ok)


def response_contains(tool: str, *needles: str) -> bool:
    """A successful call to `tool` returned a response containing all needles.

    Lets a test assert on data the agent READ (e.g. the fingerprint existed in
    the tracker) without touching any world snapshot.
    """
    for s in calls(tool):
        blob = _resp_text(s).lower()
        if all(str(n).lower() in blob for n in needles):
            return True
    return False


def final_contains(*needles: str) -> bool:
    blob = final().lower()
    return all(str(n).lower() in blob for n in needles)
