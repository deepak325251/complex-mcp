from __future__ import annotations

import re

from benchmark.mcp_traj import from_complexmcp

_TRAJ = {
    "steps": [
        # Real thinking (-> thinking block) + visible speech (-> text block).
        {"step": 1, "reasoning": "the cart may be dirty; verify before acting",
         "message": "Let me check the cart first.", "signature": ["sig_abc"],
         "tool": "get_cart_summary", "arguments": {},
         "response": {"status": "ok", "output": []}},
        {"step": 2, "reasoning": "", "message": "",
         "tool": "place_market_order", "arguments": {"ticker": "PFE", "qty": 2},
         "response": {"status": "error", "output": "internel error"}},
    ],
    "final_message": "Done: bought 2 PFE.",
}


def _doc():
    return from_complexmcp(
        _TRAJ, task_id="mcp-stump/foo", query="Buy 2 PFE.",
        taxonomy_l1="L4", taxonomy_l2="Finance Ops",
        tokens={"prompt": 100, "llm": 200, "tool": 50})


def test_top_level_schema_keys():
    d = _doc()
    # Lean complex-mcp-native shape: no file/modality cruft.
    assert set(d.keys()) == {
        "session_id", "timestamp", "meta_info", "messages", "usage"}
    assert d["session_id"] and d["timestamp"]
    for dropped in ("input_files", "output_artifacts", "trajectory"):
        assert dropped not in d


def test_meta_info_shape_and_slug():
    meta = _doc()["meta_info"]
    assert set(meta.keys()) == {"platform", "taxonomy_l1", "taxonomy_l2"}
    assert meta["platform"] == "linux"
    assert meta["taxonomy_l1"] == "L4"
    # L2 is a snake_case slug.
    assert re.fullmatch(r"[a-z0-9_]+", meta["taxonomy_l2"])
    assert meta["taxonomy_l2"] == "finance_ops"


def test_messages_are_typed_with_ids_and_turn_index():
    msgs = _doc()["messages"]
    # user + (assistant + toolResult) * 2 steps + final assistant = 6
    assert len(msgs) == 6
    assert [m["message"]["role"] for m in msgs] == [
        "user", "assistant", "toolResult", "assistant", "toolResult", "assistant"]
    for i, m in enumerate(msgs):
        assert m["type"] == "message"
        assert m["id"]
        assert "parentId" in m
        assert m["turn_index"] == i
        for block in m["message"]["content"]:
            assert block["type"] in {"thinking", "text", "toolCall", "toolResult"}


def test_parent_id_chain_links():
    msgs = _doc()["messages"]
    assert msgs[0]["parentId"] == ""
    for prev, cur in zip(msgs, msgs[1:]):
        assert cur["parentId"] == prev["id"]


def test_tool_call_and_result_blocks():
    msgs = _doc()["messages"]
    call = msgs[1]["message"]["content"][-1]  # assistant's toolCall (last block)
    assert call["type"] == "toolCall"
    assert call["id"] == "toolu_1"
    assert call["name"] == "get_cart_summary"
    # first step: real thinking -> thinking block (with signature), then visible
    # speech -> text block, then the tool call.
    first = msgs[1]["message"]["content"]
    assert [b["type"] for b in first] == ["thinking", "text", "toolCall"]
    assert first[0]["thinking"] and first[0]["signature"] == "sig_abc"
    assert first[1]["text"] == "Let me check the cart first."
    # second step has no thinking/speech -> only the tool call block
    assert [b["type"] for b in msgs[3]["message"]["content"]] == ["toolCall"]
    result = msgs[2]["message"]["content"][0]
    assert result["type"] == "toolResult"
    assert result["toolCallId"] == "toolu_1"
    assert result["details"]["status"] == "ok" and result["details"]["exitCode"] == 0
    err = msgs[4]["message"]["content"][0]
    assert err["details"]["status"] == "error" and err["details"]["exitCode"] == 1


def test_usage_maps_from_tokens():
    u = _doc()["usage"]
    assert u["input_tokens"] == 100 and u["output_tokens"] == 200
    assert set(u.keys()) == {
        "input_tokens", "output_tokens", "cached_input_tokens",
        "cache_read_tokens", "cache_write_tokens", "cost_usd"}
