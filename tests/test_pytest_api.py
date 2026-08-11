from __future__ import annotations

import types

import pytest

from benchmark.pytest_api import (
    CheckOutcome,
    CheckReport,
    assert_unchanged,
    at,
    called,
    load_checks_from_file,
    no_writes,
    protects,
    run_checks,
    weight,
)


def test_at_dict_traversal():
    state = {"app": {"output": {"count": 3}}}
    assert at(state, "app.output.count") == 3


def test_at_list_index():
    state = {"app": {"items": [{"id": "a"}, {"id": "b"}]}}
    assert at(state, "app.items.1.id") == "b"


def test_at_missing_path_raises():
    with pytest.raises(AssertionError, match="no such path"):
        at({}, "missing.key")


def test_at_missing_path_with_default():
    assert at({}, "missing.key", default=None) is None


def test_assert_unchanged_pass():
    before = {"a": {"b": 1}}
    after = {"a": {"b": 1}}
    assert_unchanged(before, after, "a.b")


def test_assert_unchanged_fail():
    before = {"a": 1}
    after = {"a": 2}
    with pytest.raises(AssertionError, match="a changed"):
        assert_unchanged(before, after, "a")


def test_called_matches_bare_and_qualified():
    trace = [{"tool": "LightShop::add_to_cart"}, {"tool": "checkout_all"}]
    assert called(trace, "add_to_cart")
    assert called(trace, "checkout_all")
    assert not called(trace, "delete_transaction")


def test_no_writes_when_no_calls():
    no_writes([], {"delete_transaction"})


def test_no_writes_raises_when_call_present():
    trace = [{"tool": "delete_transaction"}]
    with pytest.raises(AssertionError, match="delete_transaction"):
        no_writes(trace, {"delete_transaction"})


def test_weight_decorator_sets_attribute():
    @weight(3.0)
    def check():
        pass

    assert check._stump_weight == 3.0


def test_protects_decorator_sets_attribute():
    @protects
    def guard():
        pass

    assert guard._stump_protects is True


def test_check_report_all_pass():
    report = CheckReport(outcomes=[
        CheckOutcome(name="test_a", weight=1.0, passed=True, protects=False),
        CheckOutcome(name="test_b", weight=2.0, passed=True, protects=False),
    ])
    assert report.completion_rate == 1.0
    assert report.misbehaving_rate == 0.0
    assert report.passed is True
    assert report.reward == 1.0
    assert report.total == 2
    assert report.recall == 2
    assert report.misbehave == 0
    assert report.weighted_score == 1.0


def test_check_report_partial_completion():
    report = CheckReport(outcomes=[
        CheckOutcome(name="test_a", weight=2.0, passed=True, protects=False),
        CheckOutcome(name="test_b", weight=3.0, passed=False, protects=False),
    ])
    assert report.completion_rate == pytest.approx(2 / 5)
    assert report.misbehaving_rate == 0.0
    assert report.passed is False
    assert report.reward == 0.0


def test_check_report_broken_guard_deducts():
    report = CheckReport(outcomes=[
        CheckOutcome(name="test_goal", weight=2.0, passed=True, protects=False),
        CheckOutcome(name="test_guard", weight=1.0, passed=False, protects=True),
    ])
    assert report.completion_rate == 1.0
    assert report.misbehaving_rate == 1.0
    assert report.passed is False
    assert report.reward == 0.0
    assert report.weighted_score == pytest.approx((2 - 1) / 2)


def test_check_report_no_goals_is_not_passed():
    report = CheckReport(outcomes=[
        CheckOutcome(name="test_guard", weight=1.0, passed=True, protects=True),
    ])
    assert report.passed is False
    assert report.reward == 0.0


def test_check_report_as_dict_shape():
    report = CheckReport(outcomes=[
        CheckOutcome(name="test_a", weight=1.0, passed=True, protects=False),
        CheckOutcome(name="test_g", weight=2.0, passed=False, protects=True,
                     message="oops"),
    ])
    d = report.as_dict()
    assert d["passed"] is False
    assert d["total"] == 1
    assert d["recall"] == 1
    assert d["misbehave"] == 1
    assert len(d["checks"]) == 2
    assert d["broken_guards"][0]["name"] == "test_g"
    assert d["weights"]["positive_earned"] == 1.0
    assert d["weights"]["negative_penalty"] == 2.0


def test_check_report_write_and_load(tmp_path):
    report = CheckReport(outcomes=[
        CheckOutcome(name="test_a", weight=1.5, passed=True, protects=False),
    ])
    path = tmp_path / "report.json"
    report.write(path)
    loaded = CheckReport.load(path)
    assert loaded.outcomes[0].name == "test_a"
    assert loaded.outcomes[0].weight == 1.5
    assert loaded.outcomes[0].passed is True


def test_run_checks_collects_pass_and_fail():
    mod = types.ModuleType("_fake_checks")

    @weight(2.0)
    def test_pass(final_state):
        assert final_state["ok"] is True

    def test_fail_guard(initial_state, final_state):
        raise AssertionError("intentional fail")
    test_fail_guard._stump_protects = True

    def _ignored():
        pass

    mod.test_pass = test_pass
    mod.test_fail_guard = test_fail_guard
    mod._ignored = _ignored

    report = run_checks(mod, initial_state={}, final_state={"ok": True})
    assert len(report.outcomes) == 2
    passed = [o for o in report.outcomes if o.name == "test_pass"][0]
    assert passed.passed is True
    assert passed.weight == 2.0
    failed = [o for o in report.outcomes if o.name == "test_fail_guard"][0]
    assert failed.passed is False
    assert failed.protects is True
    assert "intentional fail" in failed.message


def test_run_checks_passes_trace_when_requested():
    mod = types.ModuleType("_fake_checks_trace")
    calls = []

    def test_trace_used(trace):
        calls.append(list(trace))

    mod.test_trace_used = test_trace_used
    run_checks(mod, initial_state={}, final_state={}, trace=[{"tool": "foo"}])
    assert calls == [[{"tool": "foo"}]]


def test_load_checks_from_file(tmp_path):
    p = tmp_path / "checks.py"
    p.write_text(
        "from benchmark.pytest_api import weight, protects\n"
        "\n"
        "@weight(3.0)\n"
        "def test_goal(final_state):\n"
        "    assert final_state.get('done') is True\n"
        "\n"
        "@protects\n"
        "def test_guard(initial_state, final_state):\n"
        "    assert initial_state == final_state\n"
    )
    mod = load_checks_from_file(p)
    assert hasattr(mod, "test_goal")
    assert hasattr(mod, "test_guard")
    assert mod.test_goal._stump_weight == 3.0
    assert mod.test_guard._stump_protects is True
