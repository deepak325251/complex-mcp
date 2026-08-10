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
