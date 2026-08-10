"""Emit a CTRF report directly from the judge result.

Why not just use pytest's CTRF plugin:

The plugin writes one record per parametrised test, but it drops the param id
from `name` and instead stores the *entire* parameter list in `tags` -- on
every record. With 300 negative key-paths that is 300 copies of a 50 KB repr:
15 MB of file, 99.6% of it duplicated, and every record indistinguishable from
its siblings except by timestamp. The per-key granularity the parametrisation
was supposed to buy is not actually recoverable from it.

Building the report from the JudgeResult instead gives one record per
key-path, named by that key-path, with the expected and actual values on the
failures. Same information the parametrised run was meant to produce, ~350x
smaller, and actually per-key.

CTRF schema: https://ctrf.io
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .judge import _trunc, JudgeResult, KeyOutcome

TOOL_NAME = "mcp-stump"
SCHEMA = "https://ctrf.io/schema/v1"


def _label(o: KeyOutcome) -> str:
    return ".".join(str(p) for p in o.path)


def _message(o: KeyOutcome) -> str:
    if o.ok:
        return ""
    if o.kind == "positive":
        return f"expected {_trunc(o.expected)!r}, got {_trunc(o.new)!r}"
    return f"collateral damage: was {_trunc(o.old)!r}, now {_trunc(o.new)!r}"


def build(
    result: JudgeResult,
    *,
    extra_tests: list[dict[str, Any]] | None = None,
    started: float | None = None,
    stopped: float | None = None,
) -> dict:
    """One CTRF test per scored key-path, plus any structural gates."""
    now = time.time()
    start_ms = int((started or now) * 1000)
    stop_ms = int((stopped or now) * 1000)

    tests: list[dict[str, Any]] = list(extra_tests or [])

    for o in result.outcomes:
        kind = "required_state_reached" if o.kind == "positive" else "untouched_state_unchanged"
        entry: dict[str, Any] = {
            "name": f"{kind}[{_label(o)}]",
            "status": "passed" if o.ok else "failed",
            "duration": 0,
            "filePath": "mcp_stump/verify/judge.py",
        }
        if not o.ok:
            entry["message"] = _message(o)
        tests.append(entry)

    passed = sum(1 for t in tests if t["status"] == "passed")
    failed = sum(1 for t in tests if t["status"] == "failed")

    return {
        "reportFormat": "CTRF",
        "specVersion": "0.0.0",
        "results": {
            "tool": {"name": TOOL_NAME},
            "summary": {
                "tests": len(tests),
                "passed": passed,
                "failed": failed,
                "skipped": 0,
                "pending": 0,
                "other": 0,
                "start": start_ms,
                "stop": stop_ms,
            },
            "tests": tests,
        },
    }


def envelope(tests: list[dict[str, Any]], *, started: float | None = None,
             stopped: float | None = None) -> dict:
    """Wrap already-built test records in the CTRF envelope.

    `build()` derives its records from a JudgeResult's key-paths. Authored
    checks are already named by a human, so they need the envelope without the
    key-path derivation.
    """
    now = time.time()
    return {
        "reportFormat": "CTRF",
        "specVersion": "0.0.0",
        "results": {
            "tool": {"name": TOOL_NAME},
            "summary": {
                "tests": len(tests),
                "passed": sum(1 for t in tests if t["status"] == "passed"),
                "failed": sum(1 for t in tests if t["status"] == "failed"),
                "skipped": 0, "pending": 0, "other": 0,
                "start": int((started or now) * 1000),
                "stop": int((stopped or now) * 1000),
            },
            "tests": tests,
        },
    }


def gate(name: str, ok: bool, message: str = "") -> dict[str, Any]:
    """A structural gate that is not tied to a single key-path."""
    entry: dict[str, Any] = {
        "name": name,
        "status": "passed" if ok else "failed",
        "duration": 0,
        "filePath": "mcp_stump/verify/entry.py",
    }
    if not ok and message:
        entry["message"] = message
    return entry


def write(report: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1))
    return path
