import pytest

from benchmark.authored_checks import (
    at,
    assert_unchanged,
    called,
    no_writes,
    CheckOutcome,
    CheckReport,
)


def test_at_reads_dotted_path_through_list_index():
    state = {"LightStock": {"output": {"portfolio": [{"seat": "A"}]}}}
    assert at(state, "LightStock.output.portfolio.0.seat") == "A"


def test_at_missing_path_returns_default():
    state = {"LightStock": {"output": {"portfolio": []}}}
    assert at(state, "LightStock.output.portfolio.0.seat", "fallback") == "fallback"


def test_at_missing_path_without_default_raises():
    state = {"LightStock": {"output": {"portfolio": []}}}
    with pytest.raises(AssertionError):
        at(state, "LightStock.output.portfolio.0.seat")


def test_assert_unchanged_passes_when_equal():
    before = {"LightStock": {"output": {"watch_list": ["AAA"]}}}
    after = {"LightStock": {"output": {"watch_list": ["AAA"]}}}
    assert_unchanged(before, after, "LightStock.output.watch_list")


def test_assert_unchanged_raises_when_changed():
    before = {"LightStock": {"output": {"watch_list": ["AAA"]}}}
    after = {"LightStock": {"output": {"watch_list": ["AAA", "BBB"]}}}
    with pytest.raises(AssertionError):
        assert_unchanged(before, after, "LightStock.output.watch_list")


def _report():
    return CheckReport(outcomes=[
        CheckOutcome(name="goal_pass", weight=3.0, passed=True, protects=False),
        CheckOutcome(name="goal_fail", weight=1.0, passed=False, protects=False),
        CheckOutcome(name="guard_broken", weight=2.0, passed=False, protects=True),
    ])


def test_check_report_rates_and_counts():
    r = _report()
    assert r.completion_rate == 0.75
    assert r.misbehaving_rate == 1.0
    assert r.passed is False
    assert r.total == 2
    assert r.recall == 1
    assert r.misbehave == 1


def test_check_report_as_dict_has_alias_keys():
    d = _report().as_dict()
    assert "failed_positive" in d
    assert "damaged_negative" in d
    assert "held_negative" in d


def test_no_writes_raises_when_write_tool_called():
    trace = [{"tool": "LightShop::add_to_cart", "status": "ok"}]
    with pytest.raises(AssertionError):
        no_writes(trace, ["add_to_cart"])


def test_no_writes_passes_when_no_write_tool_called():
    trace = [{"tool": "LightShop::search_items", "status": "ok"}]
    no_writes(trace, ["add_to_cart"])


def test_called_detects_bare_tool_name_from_qualified_trace():
    trace = [{"tool": "LightShop::search_items", "status": "ok"}]
    assert called(trace, "search_items") is True
    assert called(trace, "add_to_cart") is False
