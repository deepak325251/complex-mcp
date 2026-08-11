"""Tests for pass@k / pass^k / Wilson CI (benchmark/passk.py)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmark.passk import pass_at_k, pass_hat_k, wilson_ci, estimate  # noqa: E402


def test_pass_at_k_extremes():
    assert pass_at_k(8, 0, 1) == 0.0          # never passed
    assert pass_at_k(8, 8, 1) == 1.0          # always passed
    assert pass_at_k(8, 8, 8) == 1.0
    # 1 success in 8: pass@1 == 1/8; pass@8 == 1.0 (every 8-subset contains it).
    assert abs(pass_at_k(8, 1, 1) - 0.125) < 1e-9
    assert pass_at_k(8, 1, 8) == 1.0


def test_pass_at_k_unbiased_value():
    # n=4, c=2, k=2: 1 - C(2,2)/C(4,2) = 1 - 1/6.
    assert abs(pass_at_k(4, 2, 2) - (1 - 1 / 6)) < 1e-9


def test_pass_hat_k_all_succeed():
    assert pass_hat_k(8, 8, 8) == 1.0
    assert pass_hat_k(8, 1, 8) == 0.0         # can't have 8 successes from 1
    # n=4, c=2, k=2: C(2,2)/C(4,2) = 1/6.
    assert abs(pass_hat_k(4, 2, 2) - 1 / 6) < 1e-9
    # A flaky task: pass@8=1.0 but pass^8=0.0 when not every rollout passed.
    assert pass_at_k(8, 4, 8) == 1.0 and pass_hat_k(8, 4, 8) == 0.0


def test_wilson_ci_bounds():
    lo, hi = wilson_ci(0, 8)
    assert lo == 0.0 and 0.0 < hi < 1.0        # 0/8 CI excludes certainty
    lo, hi = wilson_ci(8, 8)
    assert 0.0 < lo < 1.0 and hi == 1.0


def test_estimate_shape():
    est = estimate(8, 4, [1, 2, 8])
    assert est["n"] == 8 and est["c"] == 4
    assert est["p_hat"] == 0.5
    assert set(est["pass@k"].keys()) == {"1", "2", "8"}
    assert est["pass@k"]["8"] == 1.0 and est["pass^k"]["8"] == 0.0
    # k values above n are clamped out.
    assert "16" not in estimate(8, 4, [1, 16])["pass@k"]
