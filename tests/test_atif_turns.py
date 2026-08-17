"""ATIF steps are per-LLM-TURN, carry timestamps, and their metrics sum to the total.

`parse_trajectory` reconstructs one step per TOOL CALL from a flat text stream
that records no turn boundaries. ATIF groups by turn: a turn issuing two parallel
calls is ONE step with two `tool_calls` and ONE `metrics` block. Without the
boundary that turn reads as two turns and its token slice is counted twice --
which is why `client.agent` now records `turns` and this module consumes it.

The other half: `_accumulate_usage` folds each turn into a running total and
discards the per-turn value, so step.metrics used to be unavailable at all.
"""

import json

from benchmark.atif import SCHEMA_VERSION, Trajectory, from_complexmcp


def _metrics(p, c, cached=0):
    return {"prompt_tokens": p, "completion_tokens": c, "cached_tokens": cached,
            "extra": {"cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": cached,
                      "reasoning_tokens": 0}}


PARSED = {
    "steps": [
        {"step": 1, "reasoning": "think", "message": "exploring",
         "signature": ["sig-a"], "tool": "list_dir", "arguments": {"p": "/app"},
         "response": {"status": "ok", "output": "a b"}},
        {"step": 2, "reasoning": "", "message": "",
         "tool": "read_file", "arguments": {"f": "x"},
         "response": {"status": "ok", "output": "text"}},
        {"step": 3, "reasoning": "now act", "message": "writing",
         "tool": "post", "arguments": {"body": "hi"},
         "response": {"status": "error", "output": "nope"}},
    ],
    "final_message": "done",
}

# Turn 1 emitted TWO parallel calls; turn 2 emitted none (pure text); turn 3 one.
TURNS = [
    {"timestamp": "2026-08-17T10:00:00.100Z", "metrics": _metrics(100, 10),
     "llm_call_count": 1, "n_tool_calls": 2, "stop_reason": "tool_use"},
    {"timestamp": "2026-08-17T10:00:01.100Z", "metrics": _metrics(50, 5),
     "llm_call_count": 1, "n_tool_calls": 0, "stop_reason": "end_turn"},
    {"timestamp": "2026-08-17T10:00:02.100Z", "metrics": _metrics(70, 7, cached=30),
     "llm_call_count": 1, "n_tool_calls": 1, "stop_reason": "tool_use"},
]

USAGE = {"input_tokens": 220, "output_tokens": 22, "cache_read_tokens": 30,
         "cache_creation_tokens": 0, "reasoning_tokens": 0, "cost_usd": 1.25}


def _doc(**kw):
    return from_complexmcp(PARSED, model="m", usage=USAGE, turns=TURNS,
                           session_id="sess-1", **kw)


def _agent_steps(doc):
    return [s for s in doc["steps"] if s["source"] == "agent" and s.get("tool_calls")]


def test_parallel_calls_collapse_into_one_step():
    steps = _agent_steps(_doc())
    assert len(steps) == 2                     # not 3: turn 1 issued two calls
    assert len(steps[0]["tool_calls"]) == 2
    assert [c["function_name"] for c in steps[0]["tool_calls"]] == ["list_dir", "read_file"]
    assert len(steps[1]["tool_calls"]) == 1


def test_observations_pair_with_their_calls():
    s = _agent_steps(_doc())[0]
    ids = [c["tool_call_id"] for c in s["tool_calls"]]
    assert [r["source_call_id"] for r in s["observation"]["results"]] == ids


def test_every_call_survives_grouping():
    """Grouping must never drop a tool call -- that would silently shorten the
    trajectory the model is trained on."""
    calls = Trajectory(_doc()).tool_calls()
    assert [c["function_name"] for c in calls] == ["list_dir", "read_file", "post"]


def test_step_metrics_sum_to_final_metrics():
    """The invariant that proves per-turn slices were not double-counted."""
    doc = _doc()
    steps = _agent_steps(doc)
    assert sum(s["metrics"]["prompt_tokens"] for s in steps) == 170   # 100 + 70
    assert sum(s["metrics"]["completion_tokens"] for s in steps) == 17
    # The text-only turn (50/5) emitted no step, so the document totals come from
    # the accumulator, not from re-summing steps. Both must be present and neither
    # may be silently derived from the other.
    assert doc["final_metrics"]["total_prompt_tokens"] == 220
    assert doc["final_metrics"]["total_completion_tokens"] == 22


def test_timestamps_present_and_ordered():
    ts = [s["timestamp"] for s in _agent_steps(_doc())]
    assert ts == sorted(ts)
    assert all(t.endswith("Z") for t in ts)


def test_step_keyset_matches_target_atif():
    required = {"step_id", "timestamp", "source", "message", "model_name",
                "tool_calls", "observation", "metrics", "llm_call_count", "extra"}
    assert required <= set(_agent_steps(_doc())[0])


def test_signatures_ride_in_extra_not_top_level():
    s = _agent_steps(_doc())[0]
    assert s["extra"]["reasoning_signatures"] == ["sig-a"]
    assert "reasoning_signatures" not in s


def test_tool_call_and_result_extras():
    s = _agent_steps(_doc())[0]
    c = s["tool_calls"][0]
    assert c["extra"] == {"raw_arguments": {"p": "/app"}, "tool_use_name": "list_dir"}
    assert s["observation"]["results"][0]["extra"]["tool_result_is_error"] is False


def test_error_status_is_flagged():
    s = _agent_steps(_doc())[1]           # the `post` call returned status=error
    assert s["observation"]["results"][0]["extra"]["tool_result_is_error"] is True


def test_document_header():
    doc = _doc()
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["session_id"] == "sess-1"
    assert doc["agent"]["extra"] == {}
    assert doc["final_metrics"]["total_cost_usd"] == 1.25
    assert doc["final_metrics"]["usage"] == USAGE      # nested shape retained


def test_final_message_still_resolves():
    assert Trajectory(_doc()).final_message() == "done"


def test_without_turns_falls_back_to_one_step_per_call():
    """Replayed/oracle trajectories carry no turn record; they must still convert."""
    doc = from_complexmcp(PARSED, model="m", usage=USAGE)
    steps = _agent_steps(doc)
    assert len(steps) == 3
    assert all("metrics" not in s for s in steps)
    assert all(len(s["tool_calls"]) == 1 for s in steps)


def test_undercounted_boundaries_never_drop_steps():
    """If the turn record is short (a backend that reported no usage), the
    remaining calls must still appear rather than vanish."""
    doc = from_complexmcp(PARSED, model="m", usage=USAGE, turns=TURNS[:1])
    assert len(Trajectory(doc).tool_calls()) == 3


def test_serialises():
    json.dumps(_doc())
