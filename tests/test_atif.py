from benchmark.atif import (
    SCHEMA_VERSION,
    Trajectory,
    build_pair,
    from_complexmcp,
    synth_from_trace,
)


def test_synth_from_trace_flattens_tool_calls():
    doc = synth_from_trace(
        [{"tool": "LightShop::add_to_cart", "args": {}, "response": "ok"}],
        agent="oracle",
        model="m",
    )
    assert doc["schema_version"] == "ATIF-v1.7"
    assert SCHEMA_VERSION == "ATIF-v1.7"
    calls = Trajectory(doc).tool_calls()
    assert len(calls) == 1
    assert calls[0]["function_name"] == "LightShop::add_to_cart"
    assert calls[0]["observation"] == "ok"


def test_from_complexmcp_prepends_user_prompt_step():
    traj = {"steps": [{"step": 1, "reasoning": "", "message": "ok",
                       "tool": "t", "arguments": {}, "response": "ok"}],
            "final_message": "done"}
    doc = from_complexmcp(traj, model="m", query="Clean up my account.")
    assert doc["steps"][0]["source"] == "user"
    assert doc["steps"][0]["step_id"] == 0
    assert doc["steps"][0]["message"] == "Clean up my account."
    # The user step must not disturb agent-step parsing.
    t = Trajectory(doc)
    assert t.final_message() == "done"
    assert len(t.tool_calls()) == 1
    # No query -> no synthetic user step (back-compat).
    assert from_complexmcp(traj, model="m")["steps"][0]["source"] == "agent"


def test_from_complexmcp_round_trip():
    traj = {
        "steps": [
            {
                "step": 1,
                "reasoning": "look up the user",
                "tool": "get_uid_from_name",
                "arguments": {"name": "Jeremy"},
                "response": {"status": "ok", "output": "user_XYZ"},
            },
            {
                "step": 2,
                "reasoning": "like the moment",
                "tool": "like_moment",
                "arguments": {"uid": "user_XYZ"},
                "response": "ok",
            },
        ],
        "final_message": "Done, liked the latest moment.",
    }
    doc = from_complexmcp(traj, agent="complexmcp", model="m")
    t = Trajectory(doc)

    assert doc["schema_version"] == SCHEMA_VERSION
    assert t.final_message() == "Done, liked the latest moment."

    calls = t.tool_calls()
    assert len(calls) == 2
    assert [c["function_name"] for c in calls] == ["get_uid_from_name", "like_moment"]
    # observation content is the stringified inline response, paired by call id
    assert calls[0]["observation"] == '{"status": "ok", "output": "user_XYZ"}'
    assert calls[1]["observation"] == "ok"


def test_build_pair_wires_failure_and_scores():
    failed = Trajectory(
        {
            "schema_version": SCHEMA_VERSION,
            "steps": [
                {
                    "step_id": 1,
                    "source": "agent",
                    "reasoning_content": "wrong move",
                    "tool_calls": [
                        {
                            "tool_call_id": "call_1",
                            "function_name": "search_products",
                            "arguments": {},
                        }
                    ],
                    "observation": {
                        "results": [{"source_call_id": "call_1", "content": "ok"}]
                    },
                }
            ],
        }
    )
    diagnosis = {
        "primary_failure": {
            "mode": "wrong_tool",
            "category": "over_action",
            "explanation": "used search instead of like",
        }
    }
    judge = {"completion_rate": 0.0, "misbehaving_rate": 0.0, "passed": False}

    pair = build_pair(
        task_name="t",
        seed=42,
        instruction="like the latest post",
        failed=failed,
        gold=None,
        diagnosis=diagnosis,
        judge=judge,
        env_trace=[],
        levers=["distractors"],
    )

    assert pair["failure"]["mode"] == "wrong_tool"
    assert pair["scores"]["passed"] is False
    assert pair["chosen"] is None
    assert len(pair["rejected"]["tool_calls"]) == 1
