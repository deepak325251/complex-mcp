"""Tests for ETOM pseudo-execution (client/pseudo_exec.py).

The contract: a tool call returns a world-free, success-shaped response derived
from the tool's declared ``returns``, so the agent proceeds through its plan
without any server or world.pkl. Grading is name-based (graph_judge), so the
exact values do not matter -- only that reads are non-empty and everything is ok.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from client.pseudo_exec import pseudo_output  # noqa: E402


def _out(tool: dict, args: dict | None = None):
    d = json.loads(pseudo_output(tool, args or {}))
    assert d["status"] == "ok"
    return d["output"]


def test_list_of_positions_is_nonempty_collection():
    tool = {"tool_name": "get_portfolio",
            "returns": {"type": "object",
                        "description": "output is a list of positions with ticker"}}
    out = _out(tool)
    assert isinstance(out, list) and len(out) > 1  # >1 so plan can fan out


def test_confirmation_is_a_single_object():
    tool = {"tool_name": "place_market_order",
            "returns": {"type": "object",
                        "description": "output confirms execution with fee"}}
    out = _out(tool)
    assert isinstance(out, dict)


def test_explicit_array_type_is_a_list():
    tool = {"tool_name": "list_things", "returns": {"type": "array", "description": ""}}
    assert isinstance(_out(tool), list)


def test_scalar_return_types():
    assert _out({"tool_name": "t", "returns": {"type": "string", "description": ""}}) \
        .startswith("pseudo")
    assert _out({"tool_name": "t", "returns": {"type": "boolean", "description": ""}}) is True
    assert _out({"tool_name": "t", "returns": {"type": "integer", "description": ""}}) == 1


def test_scalar_args_are_echoed_into_record():
    tool = {"tool_name": "place_market_order",
            "returns": {"type": "object", "description": "confirms"}}
    out = _out(tool, {"ticker": "PYPL", "session_id": "x", "os_cfg": {"a": 1}})
    assert out.get("ticker") == "PYPL"       # scalar echoed
    assert "session_id" not in out            # plumbing dropped
    assert "os_cfg" not in out


def test_output_is_a_json_string_like_a_real_success():
    # Toolbox.call returns the app's serialized text on success; pseudo must match.
    s = pseudo_output({"tool_name": "t", "returns": {"type": "object", "description": ""}}, {})
    assert isinstance(s, str)
    json.loads(s)  # parseable


def test_deterministic():
    tool = {"tool_name": "get_portfolio",
            "returns": {"type": "object", "description": "a list of positions"}}
    assert pseudo_output(tool, {"a": 1}) == pseudo_output(tool, {"a": 1})


def test_cache_override_wins():
    tool = {"tool_name": "get_portfolio", "returns": {"type": "object", "description": "a list of"}}
    cache = {"get_portfolio": {"output": [{"ticker": "AAPL", "quantity": 10}]}}
    out = json.loads(pseudo_output(tool, {}, cache))["output"]
    assert out == [{"ticker": "AAPL", "quantity": 10}]
