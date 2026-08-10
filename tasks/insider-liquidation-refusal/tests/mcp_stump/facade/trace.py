"""Ordered environment trace.

ATIF captures the agent's view of a run. It does not capture what the
environment did: which gate rejected a call, whether an error was the injected
transient one, or how the state moved after each mutation.

ComplexMCP's own harness has the same gap in a different form -- its
`tool_cnt` is a {tool: {status: count}} dict, so call *order* is lost entirely
and no plan-shape scoring is possible from it.

This writes one JSON object per call, in order, append-only.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


class TraceWriter:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Create the file eagerly, even though nothing has been written yet.
        # `trace.jsonl` is a declared Harbor artifact, and Harbor treats a
        # missing declared artifact as a hard trial failure -- so a run that
        # legitimately makes zero calls (the nop control, or an agent that
        # refuses) would be reported as broken infrastructure rather than as
        # the zero-call run it actually was. An empty trace is data.
        self.path.touch(exist_ok=True)
        self._lock = threading.Lock()
        self._i = 0

    def write(self, record: dict[str, Any]) -> None:
        with self._lock:
            record = {"i": self._i, **record}
            self._i += 1
            with self.path.open("a") as fh:
                fh.write(json.dumps(record, default=str) + "\n")

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]


def load_trace(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def summarize(trace: list[dict]) -> dict[str, Any]:
    """Call statistics, split the way ComplexMCP splits them.

    valid / execution-failure / syntactic-error separates model tiers before
    you look at success rate at all -- in the ComplexMCP results Llama-3.1-8B
    logged 6.46 syntactic errors per task against ~0 for frontier models.
    """
    valid = sum(1 for r in trace if r.get("status") == "ok")
    failed = sum(1 for r in trace if r.get("status") == "failed")
    errored = sum(1 for r in trace if r.get("status") == "error")
    malformed = sum(1 for r in trace if r.get("status") == "malformed")
    distractor = sum(1 for r in trace if r.get("distractor"))
    return {
        "total_calls": len(trace),
        "valid_invocations": valid,
        "execution_failures": failed,
        "errors": errored,
        "syntactic_errors": malformed,
        "distractor_calls": distractor,
        "unique_tools": len({r.get("tool") for r in trace}),
        "total_latency_ms": sum(int(r.get("latency_ms", 0)) for r in trace),
    }
