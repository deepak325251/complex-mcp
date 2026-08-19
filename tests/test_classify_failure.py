from benchmark.classify_failure import classify, parse_expected_tools
from benchmark.failure_taxonomy import FailureClass


def _score(**kw):
    base = {"passed": False, "recall": 0, "total": 1, "misbehave": 0, "reward": 0.0}
    base.update(kw)
    return base


def _tool_summary(**kw):
    base = {"valid_tool_calls": 0, "invalid_tool_calls": 0, "error_tool_calls": 0,
            "tool_cnt": {}}
    base.update(kw)
    return base


def _traj(steps=None, final=""):
    return {"steps": steps or [], "final_message": final}


def _call(trajectory, tool_summary, score, task_context, final_message, **kw):
    return classify(
        trajectory=trajectory,
        tool_summary=tool_summary,
        score=score,
        task_context=task_context,
        final_message=final_message,
        **kw,
    )


def test_passed_true_returns_unknown():
    v = _call(_traj(), _tool_summary(), _score(passed=True, recall=1), {}, "")
    assert v.failure_class == FailureClass.UNKNOWN


def test_max_turns_hit_beats_others():
    v = _call(_traj([{"step": 1, "tool": "x"}]),
              _tool_summary(valid_tool_calls=1),
              _score(), {}, "not done", max_turns_hit=True)
    assert v.failure_class == FailureClass.MAX_TURNS_EXCEEDED


def test_no_tools_and_long_final_is_refused():
    long = "I cannot help with this task because it seems risky. " * 3
    v = _call(_traj(final=long), _tool_summary(), _score(), {}, long)
    assert v.failure_class == FailureClass.REFUSED


def test_no_tools_and_short_final_is_no_tool_calls():
    v = _call(_traj(final="ok"), _tool_summary(), _score(), {}, "ok")
    assert v.failure_class in (FailureClass.NO_TOOL_CALLS, FailureClass.REFUSED)


def test_all_invalid_calls_is_format_error():
    v = _call(_traj([{"step": 1, "tool": None}]),
              _tool_summary(valid_tool_calls=0, invalid_tool_calls=3),
              _score(), {}, "")
    assert v.failure_class == FailureClass.FORMAT_ERROR


def test_wrong_tool_when_expected_disjoint():
    steps = [{"step": 1, "tool": "search_products"}]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=1,
                            tool_cnt={"search_products": {"ok": 1}}),
              _score(),
              {"expected_tools": ["like_moment", "get_uid_from_name"]},
              "")
    assert v.failure_class == FailureClass.WRONG_TOOL


def test_partial_completion_on_partial_recall():
    steps = [
        {"step": 1, "tool": "get_uid_from_name"},
        {"step": 2, "tool": "like_moment"},
    ]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=2,
                            tool_cnt={"get_uid_from_name": {"ok": 1},
                                      "like_moment": {"ok": 1}}),
              _score(recall=2, total=5),
              {"expected_tools": ["get_uid_from_name", "like_moment"]},
              "")
    assert v.failure_class in (FailureClass.PARTIAL_COMPLETION, FailureClass.UNKNOWN)


def test_parse_expected_tools_from_dict():
    assert parse_expected_tools({"foo": {"ok": 1}, "bar": {"ok": 2}}) == ["foo", "bar"]


def test_parse_expected_tools_from_json_str():
    assert parse_expected_tools('{"foo": 1, "bar": 2}') == ["foo", "bar"]


def test_parse_expected_tools_bad_input():
    assert parse_expected_tools(None) == []
    assert parse_expected_tools("not-json") == []


def test_gate_signature_triggers_missing_prereq():
    steps = [
        {"step": 1, "tool": "checkout_all",
         "response": {"status": "error", "message": "Please enter the payment password"}},
    ]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=0, invalid_tool_calls=0, error_tool_calls=1),
              _score(),
              {"expected_tools": ["checkout_all", "wait_payment_password"]},
              "")
    assert v.failure_class == FailureClass.MISSING_PREREQ
    assert v.evidence["opener"] == "wait_payment_password"


def test_gate_recovered_does_not_trigger_missing_prereq():
    steps = [
        {"step": 1, "tool": "checkout_all",
         "response": {"status": "error", "message": "Please enter the payment password"}},
        {"step": 2, "tool": "wait_payment_password", "response": {"status": "ok"}},
        {"step": 3, "tool": "checkout_all", "response": {"status": "ok"}},
    ]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=3),
              _score(recall=1, total=1),
              {},
              "")
    assert v.failure_class != FailureClass.MISSING_PREREQ


def test_distractor_saturation_becomes_distraction_derailed():
    steps = [{"step": 1, "tool": "search_hotels"}]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=1, tool_cnt={"search_hotels": {"ok": 1}}),
              _score(),
              {"expected_tools": ["search_flights"],
               "stump_levers": ["distractor_saturation"]},
              "")
    assert v.failure_class == FailureClass.DISTRACTION_DERAILED
    assert v.evidence["crux_aligned"] is True


def test_transient_defeatism_is_err_recovery():
    steps = [
        {"step": 1, "tool": "like_moment",
         "response": {"status": "error", "message": "network issue please try again"}},
    ]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=0, invalid_tool_calls=0, error_tool_calls=1),
              _score(),
              {"stump_levers": ["transient_failure"]},
              "")
    assert v.failure_class == FailureClass.ERR_RECOVERY
    assert v.evidence["crux_aligned"] is True


def test_over_action_when_misbehave_and_recall():
    steps = [
        {"step": 1, "tool": "buy_stock", "response": {"status": "ok"}},
        {"step": 2, "tool": "liquidate_all", "response": {"status": "ok"}},
    ]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=2),
              _score(recall=2, total=2, misbehave=1),
              {"stump_levers": ["dirty_state"]},
              "")
    assert v.failure_class == FailureClass.OVER_ACTION
    assert v.evidence["crux_aligned"] is True


def test_clean_slate_bias_when_first_action_is_write():
    steps = [
        {"step": 1, "tool": "add_to_cart", "response": {"status": "ok"}},
        {"step": 2, "tool": "checkout_all", "response": {"status": "ok"}},
    ]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=2),
              _score(recall=0, total=3, misbehave=2),
              {"stump_levers": ["dirty_state"]},
              "")
    assert v.failure_class in (FailureClass.OVER_ACTION, FailureClass.CLEAN_SLATE_BIAS)


def test_crux_aligned_false_when_lever_mismatches():
    steps = [{"step": 1, "tool": "search_products"}]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=1),
              _score(),
              {"expected_tools": ["like_moment"],
               "stump_levers": ["hidden_prerequisite"]},
              "")
    assert v.failure_class == FailureClass.WRONG_TOOL
    assert v.evidence["crux_aligned"] is False


def test_dirty_state_ignored_when_agent_skips_a_nonempty_list():
    steps = [
        {"step": 1, "tool": "list_alerts",
         "response": {"status": "ok", "output": [{"aid": "stale_1"}]}},
    ]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=1, tool_cnt={"list_alerts": {"ok": 1}}),
              _score(recall=1, total=3, misbehave=0),
              {"stump_levers": ["dirty_state"]},
              "")
    assert v.failure_class == FailureClass.DIRTY_STATE_IGNORED


def test_dirty_state_becomes_environment_mismatch_when_world_is_empty():
    # Regression: whitfield-reunion-cookout -- list_alerts() legitimately
    # returned [] because the world was never seeded with the declared
    # alerts. The agent read an empty collection; it had nothing to clean.
    steps = [
        {"step": 1, "tool": "get_primary_location",
         "response": {"status": "ok", "output": "Savannah"}},
        {"step": 2, "tool": "list_alerts",
         "response": {"status": "ok", "output": []}},
    ]
    v = _call(_traj(steps),
              _tool_summary(valid_tool_calls=2,
                            tool_cnt={"get_primary_location": {"ok": 1},
                                      "list_alerts": {"ok": 1}}),
              _score(recall=2, total=9, misbehave=0),
              {"stump_levers": ["dirty_state"]},
              "")
    assert v.failure_class == FailureClass.ENVIRONMENT_MISMATCH


def test_bare_and_qualified_tool_names_normalize():
    from benchmark.classify_failure import _base
    assert _base("LightShop::checkout_all") == "checkout_all"
    assert _base("checkout_all") == "checkout_all"
    assert _base(None) == ""
    assert _base("") == ""
