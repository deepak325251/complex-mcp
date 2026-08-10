from benchmark.failure_taxonomy import (
    FailureClass,
    FailureVerdict,
    FAILURE_DESCRIPTIONS,
)


def test_all_failure_classes_have_description():
    for fc in FailureClass:
        assert fc in FAILURE_DESCRIPTIONS, fc
        assert FAILURE_DESCRIPTIONS[fc], fc


def test_failure_class_str_is_stable():
    assert FailureClass.REFUSED.value == "refused"
    assert FailureClass.UNKNOWN.value == "unknown"


def test_verdict_to_dict_roundtrip():
    v = FailureVerdict(
        failure_class=FailureClass.FORMAT_ERROR,
        reason="bad json in tool block",
        evidence={"invalid": 2, "valid": 0},
    )
    d = v.to_dict()
    assert d["failure_class"] == "format_error"
    assert d["reason"] == "bad json in tool block"
    assert d["evidence"] == {"invalid": 2, "valid": 0}


def test_verdict_explicit_no_evidence():
    v = FailureVerdict(
        failure_class=FailureClass.UNKNOWN,
        reason="ok",
        evidence=None,
    )
    d = v.to_dict()
    assert d["evidence"] is None
