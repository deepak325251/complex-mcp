"""classify() must not call plan-fallback numbers 'partial state changes'."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from benchmark.classify_failure import classify


def _score(**kw):
    base = {"recall": 6, "total": 16, "misbehave": 30, "reward": 0.07}
    base.update(kw)
    return base


def _call(score):
    return classify(
        trajectory={"steps": [{"tool": "a"}, {"tool": "b"}]},
        tool_summary={"valid_tool_calls": 35},
        score=score,
    )


def test_inadmissible_state_not_called_state_change():
    # plan-fallback numbers on an empty-dump run -> honest wording, no state claim.
    v = _call(_score(state_admissible=False, misbehave_kind="plan_fp",
                     state_reason="empty_dump:LightJira"))
    assert "partial state changes" not in v.reason
    assert "state channel unavailable" in v.reason
    assert v.evidence.get("state_admissible") is False


def test_admissible_state_keeps_state_wording():
    v = _call(_score(state_admissible=True, misbehave_kind="state_guard",
                     misbehave=0))
    assert "partial state changes" in v.reason
