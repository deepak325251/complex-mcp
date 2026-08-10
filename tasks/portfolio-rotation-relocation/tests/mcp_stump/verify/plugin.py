"""pytest plugin: fixtures for authored checks, and outcome collection.

A task's `tests/checks.py` gets `initial_state`, `final_state`, `trace` and
`final_message` as fixtures and writes plain asserts. This plugin turns the
results into a CheckReport.

Registered from the task's conftest.py:

    pytest_plugins = ["mcp_stump.verify.plugin"]

Why a plugin rather than reading pytest's own report: the CTRF plugin drops the
param id from `name` and copies the whole parameter list into `tags` on every
record -- that is what produced a 15 MB report that was 99.6% duplicated
strings. Reading our own outcomes keeps the weight and the protects flag, which
no generic reporter knows about.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from . import pytest_api
from .pytest_api import CheckOutcome, CheckReport

ARTIFACT_DIR = Path(os.environ.get("MCP_STUMP_ARTIFACTS", "/logs/artifacts"))
TASK_DIR = Path(os.environ.get("MCP_STUMP_TASK_DIR", "/tests"))
VERIFIER_DIR = Path(os.environ.get("MCP_STUMP_VERIFIER_DIR", "/logs/verifier"))

_REPORT = CheckReport()


def _load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    text = path.read_text().strip()
    if not text:
        return default
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def _first(*candidates: Path, default: Any = None) -> Any:
    for c in candidates:
        got = _load(c)
        if got:
            return got
    return default


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def initial_state() -> dict:
    """The world at t=0, before the agent touched anything."""
    return _first(TASK_DIR / "initial_state.json",
                  ARTIFACT_DIR / "initial_state.json",
                  ARTIFACT_DIR / "tmp" / "initial_state.json",
                  Path("/tmp/initial_state.json"), default={})


@pytest.fixture(scope="session")
def final_state() -> dict:
    """The world after the agent stopped.

    Arrives via Harbor's [[verifier.collect]] hook, so it exists whether or not
    the agent called anything -- which is what makes an L5 refusal gradeable.

    Separate-mode verifiers rematerialise collected artifacts at their ORIGINAL
    absolute paths, so a sidecar's /tmp/x lands at /tmp/x, not under
    /logs/artifacts. Check both.
    """
    # Harbor rematerialises a collected artifact at its ORIGINAL absolute
    # path, so a sidecar's /tmp/x lands at /tmp/x. The nested artifacts/tmp/
    # form is the on-disk layout of the harvested trial dir; accepting both
    # means the same checks run identically against a live verifier and
    # against a preserved bundle.
    return _first(ARTIFACT_DIR / "final_state.json",
                  ARTIFACT_DIR / "tmp" / "final_state.json",
                  Path("/tmp/final_state.json"), default={})


@pytest.fixture(scope="session")
def trace() -> list[dict]:
    """The facade's ordered record of every call. Empty list is valid data."""
    return _first(ARTIFACT_DIR / "trace.jsonl",
                  ARTIFACT_DIR / "tmp" / "trace.jsonl",
                  Path("/tmp/trace.jsonl"), default=[])


def resolve_final_message() -> str:
    """The agent's closing text, for checks about what it *claimed*.

    Shared with verify.entry rather than reimplemented: the checks and the
    scorer must read the SAME message, or a task can pass its authored checks
    against one string while the rubric grades another. An earlier version had
    the fallback in only one of the two, and the refusal oracle failed its own
    closing-message check while the rubric saw the text fine.
    """
    # /logs IS the trial directory inside the verifier -- it is where this
    # process writes verifier/checks.json -- so the agent phase's output is
    # reachable at /logs/agent/trajectory.json. Nothing collects the trajectory
    # as an artifact (it is written host-side, not in a service container), so
    # without this the verifier never sees the agent's closing message: the
    # closing-message check fails on a correct run and the rubric grades an
    # empty string, which is every judged criterion lost.
    for base in (ARTIFACT_DIR.parent / "agent", ARTIFACT_DIR, Path("/tmp"),
                 Path("/logs/agent")):
        tj = _load(base / "trajectory.json")
        for step in reversed((tj or {}).get("steps", [])):
            if step.get("source") == "agent" and step.get("message"):
                return str(step["message"])
    # Oracle control on a refusal task: a script emits no ATIF message.
    for p in (ARTIFACT_DIR / "final_message.txt", Path("/tmp/final_message.txt")):
        if p.is_file():
            return p.read_text()
    return ""


@pytest.fixture(scope="session")
def final_message() -> str:
    return resolve_final_message()


@pytest.fixture(scope="session")
def world(initial_state, final_state, trace, final_message) -> dict:
    """Everything at once, for checks that need several inputs."""
    return {"initial": initial_state, "final": final_state,
            "trace": trace, "final_message": final_message}


# --------------------------------------------------------------------------
# collection
# --------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "weight(value): contribution of this check")
    config.addinivalue_line("markers", "protects: a thing that must NOT change (Rb)")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return

    fn = getattr(item, "function", None)
    w = getattr(fn, "_stump_weight", None)
    if w is None:
        m = item.get_closest_marker("weight")
        w = float(m.args[0]) if m and m.args else 1.0
    guard = bool(getattr(fn, "_stump_protects", False)
                 or item.get_closest_marker("protects"))

    _REPORT.outcomes.append(CheckOutcome(
        name=item.name, weight=float(w), passed=report.passed,
        protects=guard,
        message="" if report.passed else str(report.longrepr or "")[:2000],
    ))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Persist the report even on collection error -- a verifier that writes
    nothing is indistinguishable from one that passed."""
    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
    _REPORT.write(VERIFIER_DIR / "checks.json")


def current_report() -> CheckReport:
    return _REPORT
