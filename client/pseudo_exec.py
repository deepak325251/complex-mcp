"""ETOM-style pseudo tool execution -- no world, no state, no server.

complex-mcp normally POSTs every tool call to a live stateful app (LightStock,
LightTalk, ...) whose world.pkl fixture must already contain whatever the task
acts on. That coupling is exactly what ETOM drops: in ETOM the agent never
executes against a world, it merely *selects* tools, and each call returns a
schema-shaped PSEUDO output (generated offline from the tool's declared return
description). The rollout is then graded purely on the tool DAG it produced
(benchmark/graph_judge), never on world state.

This module reproduces that. `pseudo_output(tool, arguments)` returns a
success-shaped response derived from the tool's ``returns`` metadata (the same
``{"type","description"}`` block ETOM's generate_pseudo_output_schema.py reads),
so:

  * a read tool ("list your positions") returns a plausible NON-EMPTY collection,
    so the agent believes there is something to act on and proceeds through the
    plan (the concrete values are irrelevant -- the graph grader matches on tool
    NAME, not arguments);
  * an action tool ("place order") returns ``status: ok`` so no error branch is
    taken.

Determinism: ids are derived from the tool name + a call index (no RNG), so a
given trajectory is reproducible.

An optional offline cache (client/pseudo_schemas/<Server>.json, mapping
tool_name -> example output) is honoured if present -- that is where an
LLM-generated, higher-fidelity ETOM schema would live. Absent, the heuristic
below is used, which is enough for structural (tool-DAG) grading.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict

_SCHEMA_DIR = Path(__file__).resolve().parent / "pseudo_schemas"

# A COLLECTION is signalled by the return description literally saying the output
# IS a list/array of things ("output is a list of positions"). Every tool here
# wraps its payload as "A dictionary containing status and output. On success,
# output is a list of ...", so this phrase -- not loose plural nouns -- is the
# reliable discriminator between a read-many (list) and a confirm/read-one (object).
_COLLECTION_HINTS = re.compile(r"\b(?:a\s+)?(?:list|array)\s+of\b", re.IGNORECASE)


def _load_cache() -> Dict[str, Any]:
    """tool_name -> example output, merged across client/pseudo_schemas/*.json."""
    cache: Dict[str, Any] = {}
    if not _SCHEMA_DIR.is_dir():
        return cache
    for f in sorted(_SCHEMA_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            cache.update(data)
    return cache


def _record(tool_name: str, i: int, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """One plausible, deterministic record. Small subset of scalar args echoed
    back so a value the agent passed in can appear to 'exist'."""
    rec: Dict[str, Any] = {
        "id": f"pseudo_{tool_name}_{i}",
        "name": f"pseudo-{tool_name}-{i}",
        "status": "ok",
        "value": i + 1,
    }
    for k, v in (arguments or {}).items():
        if k in ("session_id", "os_cfg"):
            continue
        if isinstance(v, (str, int, float, bool)):
            rec[k] = v
    return rec


def _shape(tool_name: str, returns: Dict[str, Any], arguments: Dict[str, Any]) -> Any:
    typ = str(returns.get("type", "object")).lower()
    desc = str(returns.get("description", ""))
    is_collection = typ in ("array", "list") or bool(_COLLECTION_HINTS.search(desc))
    if is_collection:
        # >1 element so plan-fan-out (one action per item) is possible.
        return [_record(tool_name, i, arguments) for i in range(3)]
    if typ in ("string", "str"):
        return f"pseudo result for {tool_name}"
    if typ in ("boolean", "bool"):
        return True
    if typ in ("number", "integer", "int", "float"):
        return 1
    # object / unknown
    return _record(tool_name, 0, arguments)


def pseudo_output(tool: Dict[str, Any], arguments: Dict[str, Any] | None = None,
                  cache: Dict[str, Any] | None = None) -> str:
    """A success-shaped, world-free response for `tool`, as a JSON string.

    Matches the shape of a real successful Toolbox.call (which returns the app's
    serialized ``{"status": "ok", "output": ...}`` text), so downstream parsing
    is unchanged.
    """
    arguments = arguments or {}
    tool_name = tool.get("tool_name", "tool")

    if cache is not None and tool_name in cache:
        payload = cache[tool_name]
        out = payload.get("output", payload) if isinstance(payload, dict) else payload
    else:
        out = _shape(tool_name, tool.get("returns", {}) or {}, arguments)

    return json.dumps({"status": "ok", "output": out}, ensure_ascii=False)


# Loaded once at import; cheap and read-only.
PSEUDO_CACHE: Dict[str, Any] = _load_cache()


def is_enabled() -> bool:
    """ETOM pseudo-execution is on iff ETOM_PSEUDO=1 in the environment."""
    return os.environ.get("ETOM_PSEUDO") == "1"
