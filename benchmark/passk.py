"""pass@k, pass^k, and Wilson confidence intervals for multi-attempt runs.

Two estimators, because they answer different questions and a stumping corpus
needs both:

  pass@k   the UNBIASED estimator 1 - C(n-c, k)/C(n, k) -- the probability that
           at least one of k rollouts succeeds, given c successes in n samples.
           This is NOT "did any of my first k pass"; it is the expectation over
           all k-subsets, which is what makes it comparable across runs with
           different n.

  pass^k   C(c, k)/C(n, k) -- the probability that ALL k rollouts succeed. The
           stability companion: a task at pass@8 == 1.0 with pass^8 == 0.0 is
           flaky, not solved, and for a stumping corpus that distinction is the
           whole signal.

`p_hat` is the raw success rate c/n; the Wilson interval is its CI95, which is
better-behaved than the normal approximation at the 0/n and n/n extremes that a
stump corpus lives at.
"""

from __future__ import annotations

from math import comb, sqrt


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased P(at least one of k succeeds) = 1 - C(n-c, k)/C(n, k)."""
    if k <= 0 or n <= 0:
        return 0.0
    if k > n:
        k = n
    if c <= 0:
        return 0.0
    if n - c < k:
        # Fewer than k failures exist, so every k-subset contains a success.
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """P(all k succeed) = C(c, k)/C(n, k)."""
    if k <= 0 or n <= 0 or c < k:
        return 0.0
    if k > n:
        return 0.0
    return comb(c, k) / comb(n, k)


def wilson_ci(c: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. Returns (lo, hi)."""
    if n <= 0:
        return (0.0, 0.0)
    phat = c / n
    denom = 1.0 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    margin = (z * sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def estimate(n: int, c: int, ks: list[int]) -> dict:
    """Full multi-attempt summary for `c` successes out of `n` rollouts."""
    ks = sorted({k for k in ks if k >= 1 and k <= n}) or ([n] if n else [])
    lo, hi = wilson_ci(c, n)
    return {
        "n": n,
        "c": c,
        "p_hat": round(c / n, 6) if n else 0.0,
        "ci95": [round(lo, 6), round(hi, 6)],
        "pass@k": {str(k): round(pass_at_k(n, c, k), 6) for k in ks},
        "pass^k": {str(k): round(pass_hat_k(n, c, k), 6) for k in ks},
    }
