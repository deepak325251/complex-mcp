"""
Converts parse_trajectory() output -- the flat shape
`{steps: [{step, reasoning, tool, arguments, response}], final_message}` -- into
a lean, message-based trajectory:

    {session_id, timestamp, meta_info, messages[], usage}

This keeps the parts of the reference message-based schema that are actually
useful for complex-mcp, and drops the parts that only make sense in a
file/multimodal task world:

  KEPT   typed content blocks (`text`/`toolCall`/`toolResult`), message id +
         parentId chain + turn_index, tool-call ids linking call<->result,
         tool-result status/exitCode, a lean taxonomy meta_info, token usage.
  DROPPED input_files/output_artifacts (complex-mcp is state-diff graded, no
         file artifacts), input/output modalities + modality tags (text-only),
         and the is_accepted/hints turn-feedback wrapper (single-shot runs).

The agent.log does not capture real model `thinking` or per-tool timing, so
reasoning text maps to a `text` block (not `thinking`) and durationMs is left
null; a future client-instrumentation pass can fill those without changing this
shape.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_ZERO_USAGE: dict[str, Any] = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cached_input_tokens": 0,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
    "cost_usd": 0.0,
}


def _slug_l2(name: str) -> str:
    return _SLUG_RE.sub("_", (name or "").lower()).strip("_")


def _coerce_usage(tokens: Optional[dict], usage: Optional[dict] = None) -> dict:
    """Build the usage block.

    Prefers the real API usage (`usage`, incl. prompt-cache read/creation and
    cost) when present; otherwise falls back to complex-mcp's estimated
    {prompt, llm, tool} token record.
    """
    def _i(src: dict, key: str) -> int:
        try:
            return int((src or {}).get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    out = dict(_ZERO_USAGE)
    if isinstance(usage, dict) and usage:
        out["input_tokens"] = _i(usage, "input_tokens")
        out["output_tokens"] = _i(usage, "output_tokens")
        out["cache_read_tokens"] = _i(usage, "cache_read_tokens")
        out["cache_write_tokens"] = _i(usage, "cache_creation_tokens")
        out["cached_input_tokens"] = out["cache_read_tokens"] + out["cache_write_tokens"]
        try:
            out["cost_usd"] = float(usage.get("cost_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            out["cost_usd"] = 0.0
        return out

    if isinstance(tokens, dict):
        out["input_tokens"] = _i(tokens, "prompt")
        out["output_tokens"] = _i(tokens, "llm")
    return out


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def _tool_call_block(call_id: str, name: Any, arguments: Any) -> dict:
    return {"type": "toolCall", "id": call_id, "name": name,
            "arguments": arguments if arguments is not None else {}}


def _tool_result_block(call_id: str, response: Any) -> dict:
    if isinstance(response, dict):
        status = str(response.get("status") or "ok")
    elif response is None:
        status = "error"
    else:
        status = "ok"
    content = response if isinstance(response, str) else json.dumps(response, default=str)
    return {
        "type": "toolResult",
        "toolCallId": call_id,
        "content": content,
        "details": {
            "status": status,
            "exitCode": 0 if status == "ok" else 1,
            "durationMs": None,  # not captured in agent.log; client pass can fill
        },
    }


def from_complexmcp(
    traj: dict,
    *,
    task_id: str = "",
    query: str = "",
    taxonomy_l1: str = "",
    taxonomy_l2: str = "",
    model: str = "",
    tokens: Optional[dict] = None,
    usage: Optional[dict] = None,
    timestamp: Optional[str] = None,
) -> dict:
    """Build a message-based golden trajectory document from a parse_trajectory() dict."""
    del task_id, model  # accepted for caller symmetry; not part of this schema
    ts = timestamp or datetime.now(timezone.utc).isoformat()

    messages: list[dict] = []
    parent = ""

    def _add(role: str, content: list[dict]) -> None:
        nonlocal parent
        mid = uuid.uuid4().hex
        messages.append({
            "type": "message",
            "id": mid,
            "parentId": parent,
            "timestamp": ts,
            "message": {"role": role, "content": content},
        })
        parent = mid

    # Opening user turn: the task prompt.
    if query:
        _add("user", [_text_block(query)])

    for step in traj.get("steps", []):
        call_id = "toolu_%s" % step.get("step")
        assistant_content: list[dict] = []
        reasoning = (step.get("reasoning") or "").strip()
        if reasoning:
            assistant_content.append(_text_block(reasoning))
        assistant_content.append(
            _tool_call_block(call_id, step.get("tool"), step.get("arguments")))
        _add("assistant", assistant_content)
        _add("toolResult", [_tool_result_block(call_id, step.get("response"))])

    final_message = (traj.get("final_message") or "").strip()
    if final_message:
        _add("assistant", [_text_block(final_message)])

    for idx, m in enumerate(messages):
        m["turn_index"] = idx

    return {
        "session_id": str(uuid.uuid4()),
        "timestamp": ts,
        "meta_info": {
            "platform": "linux",
            "taxonomy_l1": taxonomy_l1 or "",
            "taxonomy_l2": _slug_l2(taxonomy_l2),
        },
        "messages": messages,
        "usage": _coerce_usage(tokens, usage),
    }
