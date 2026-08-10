"""Run metrics and the summary artifact.

pass@k is the unbiased estimator from Codex/HumanEval, not "did any of my k
samples pass". With n samples and c successes:

    pass@k = 1 - C(n-c, k) / C(n, k)

That matters here because we screen at one n and report at several k. Taking
`any(successes[:k])` throws away information and is biased by sample order.

pass^k (all k succeed) is the stability companion, borrowed from MCPMark. A
task at pass@8 = 1.0 and pass^8 = 0.1 is not solved -- it is flaky, and for a
stumping corpus that difference is the whole signal.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k: probability that a random k-subset of n contains a success."""
    if k > n:
        raise ValueError(f"pass@{k} requires at least {k} samples, got {n}")
    if c == 0:
        return 0.0
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_pow_k(n: int, c: int, k: int) -> float:
    """pass^k: probability that ALL of a random k-subset succeed."""
    if k > n:
        raise ValueError(f"pass^{k} requires at least {k} samples, got {n}")
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)


def wilson_interval(n: int, c: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for the underlying success probability.

    Reported alongside the point estimate because a tier label from 8 samples
    is not a measurement -- an RL curriculum should sort on the estimate and
    its uncertainty, not on the bucket.
    """
    if n == 0:
        return (0.0, 1.0)
    p = c / n
    d = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass
class Usage:
    """Token and cost accounting for one rollout.

    Harbor populates these on `agent_result` for real agents; oracle and nop
    make no LLM calls so theirs are legitimately empty. ATIF `final_metrics`
    carries the same numbers and is used as a fallback.

    Reported because a difficulty knob that inflates context is not free: both
    source papers found prompt repetition dominating total spend, so accuracy
    without cost is an unfalsifiable claim.
    """

    input_tokens: int | None = None
    cache_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    llm_calls: int | None = None
    # Token ids / logprobs -- only terminus-family agents collect these, and
    # only with collect_rollout_details=True. Needed for RL, absent for
    # CLI-style agents like claude-code.
    has_rollout_details: bool = False

    @property
    def empty(self) -> bool:
        return self.input_tokens is None and self.output_tokens is None and self.cost_usd is None

    @classmethod
    def from_harbor(cls, agent_result: dict | None, atif_metrics: dict | None = None) -> "Usage":
        ar = agent_result or {}
        am = atif_metrics or {}
        return cls(
            input_tokens=ar.get("n_input_tokens") or am.get("total_prompt_tokens"),
            cache_tokens=ar.get("n_cache_tokens") or am.get("total_cached_tokens"),
            output_tokens=ar.get("n_output_tokens") or am.get("total_completion_tokens"),
            cost_usd=ar.get("cost_usd") if ar.get("cost_usd") is not None
                     else am.get("total_cost_usd"),
            llm_calls=am.get("total_steps"),
            has_rollout_details=bool(ar.get("rollout_details")),
        )

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "cache_tokens": self.cache_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6) if self.cost_usd is not None else None,
            "llm_calls": self.llm_calls,
            "has_rollout_details": self.has_rollout_details,
        }


@dataclass
class AttemptResult:
    attempt: int
    passed: bool
    completion_rate: float
    misbehaving_rate: float
    graph_f1: float
    reward: float
    weighted_score: float
    primary_mode: str
    crux_aligned: bool | None
    call_stats: dict = field(default_factory=dict)
    duration_sec: float = 0.0
    trajectory_path: str | None = None
    usage: Usage = field(default_factory=Usage)

    def as_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "passed": self.passed,
            "reward": self.reward,
            "completion_rate": round(self.completion_rate, 6),
            "misbehaving_rate": round(self.misbehaving_rate, 6),
            "graph_f1": round(self.graph_f1, 6),
            "weighted_score": round(self.weighted_score, 6),
            "primary_mode": self.primary_mode,
            "crux_aligned": self.crux_aligned,
            "call_stats": self.call_stats,
            "usage": self.usage.as_dict(),
            "duration_sec": round(self.duration_sec, 2),
            "trajectory": self.trajectory_path,
        }


@dataclass
class TaskSummary:
    task_name: str
    model: str
    agent: str
    seed: int
    levers: list[str]
    attempts: list[AttemptResult]
    ks: Sequence[int] = (1, 2, 8)
    oracle_reward: float | None = None
    nop_reward: float | None = None

    # -- derived ----------------------------------------------------------

    @property
    def n(self) -> int:
        return len(self.attempts)

    @property
    def c(self) -> int:
        return sum(1 for a in self.attempts if a.passed)

    def metrics(self) -> dict:
        out: dict = {}
        for k in sorted(set(self.ks)):
            if k > self.n:
                out[f"pass@{k}"] = None
                out[f"pass^{k}"] = None
                out[f"_note_k{k}"] = f"needs n>={k}, have n={self.n}"
                continue
            out[f"pass@{k}"] = round(pass_at_k(self.n, self.c, k), 6)
            out[f"pass^{k}"] = round(pass_pow_k(self.n, self.c, k), 6)
        lo, hi = wilson_interval(self.n, self.c)
        out["p_hat"] = round(self.c / self.n, 6) if self.n else None
        out["ci95"] = [round(lo, 6), round(hi, 6)]
        out["n"] = self.n
        out["c"] = self.c
        return out

    def validity(self) -> dict:
        """Is this task admissible at all?

        A stump is only real if the oracle solves it and nop does not. Without
        both controls a 0/n result is indistinguishable from a broken task --
        and a broken task labelled 'expert' poisons the corpus.
        """
        problems: list[str] = []
        if self.oracle_reward is None:
            problems.append("oracle not run")
        elif self.oracle_reward < 1.0:
            problems.append(f"oracle scored {self.oracle_reward} (must be 1.0)")
        if self.nop_reward is None:
            problems.append("nop not run")
        elif self.nop_reward > 0.0:
            problems.append(f"nop scored {self.nop_reward} (must be 0.0)")

        aligned = [a.crux_aligned for a in self.attempts if not a.passed]
        known = [a for a in aligned if a is not None]
        crux_rate = (sum(1 for a in known if a) / len(known)) if known else None
        if crux_rate is not None and crux_rate < 0.5:
            problems.append(
                f"only {crux_rate:.0%} of failures match the declared levers "
                f"-- unintended difficulty"
            )

        # Judge nearness on the sub-goal-balanced score. Raw Rc counts
        # key-paths, so a run that skipped an entire sub-goal still scores high
        # when that sub-goal happens to write few leaves.
        near = [a for a in self.attempts
                if not a.passed and a.weighted_score >= 0.9 and a.misbehaving_rate == 0]
        near_rate = len(near) / self.n if self.n else 0.0
        if near_rate >= 0.5:
            problems.append(
                f"{near_rate:.0%} of failures are near misses (Rc>=0.9, Rb=0) "
                f"-- the threshold may be doing the work, not the task"
            )

        return {
            "admissible": not problems,
            "problems": problems,
            "crux_alignment_rate": crux_rate,
            "near_miss_rate": round(near_rate, 4),
        }

    def failure_breakdown(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in self.attempts:
            if a.passed:
                continue
            counts[a.primary_mode] = counts.get(a.primary_mode, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def usage(self) -> dict:
        """Roll up token and cost accounting across attempts.

        `cost_per_solve` is the number that matters when comparing knob
        settings: a configuration that halves the solve rate while doubling
        context is much more expensive than the accuracy delta suggests.
        """
        us = [a.usage for a in self.attempts if not a.usage.empty]
        if not us:
            return {"measured_attempts": 0, "note": "no LLM usage reported "
                    "(scripted agent, or oracle/nop controls)"}

        def total(attr: str) -> float:
            return sum(getattr(u, attr) or 0 for u in us)

        cost = total("cost_usd")
        return {
            "measured_attempts": len(us),
            "total_input_tokens": int(total("input_tokens")),
            "total_cache_tokens": int(total("cache_tokens")),
            "total_output_tokens": int(total("output_tokens")),
            "total_cost_usd": round(cost, 6),
            "mean_cost_usd": round(cost / len(us), 6),
            "cost_per_solve_usd": round(cost / self.c, 6) if self.c else None,
            # Both papers found prompt repetition dominating spend; this makes
            # that visible per task instead of per programme.
            "prompt_share_of_tokens": round(
                total("input_tokens") / (total("input_tokens") + total("output_tokens")), 4
            ) if (total("input_tokens") + total("output_tokens")) else None,
            "cache_hit_rate": round(total("cache_tokens") / total("input_tokens"), 4)
                              if total("input_tokens") else None,
            "rollout_details_available": any(u.has_rollout_details for u in us),
        }

    def as_dict(self) -> dict:
        rates = [a.completion_rate for a in self.attempts]
        return {
            "task": self.task_name,
            "model": self.model,
            "agent": self.agent,
            "seed": self.seed,
            "levers": self.levers,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "controls": {"oracle_reward": self.oracle_reward, "nop_reward": self.nop_reward},
            "metrics": self.metrics(),
            "validity": self.validity(),
            "aggregate": {
                "mean_completion_rate": round(statistics.fmean(rates), 6) if rates else 0.0,
                "mean_misbehaving_rate": round(
                    statistics.fmean([a.misbehaving_rate for a in self.attempts]), 6
                ) if self.attempts else 0.0,
                "mean_graph_f1": round(
                    statistics.fmean([a.graph_f1 for a in self.attempts]), 6
                ) if self.attempts else 0.0,
            },
            "usage": self.usage(),
            "failure_breakdown": self.failure_breakdown(),
            "attempts": [a.as_dict() for a in self.attempts],
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2))
        return path


def write_job_summary(summaries: list[TaskSummary], out: Path, ks: Sequence[int]) -> Path:
    """Roll per-task summaries into one job-level artifact."""
    admissible = [s for s in summaries if s.validity()["admissible"]]
    rows = [s.as_dict() for s in summaries]

    corpus: dict = {"tasks": len(summaries), "admissible": len(admissible)}
    for k in sorted(set(ks)):
        vals = [
            s.metrics().get(f"pass@{k}")
            for s in admissible
            if s.metrics().get(f"pass@{k}") is not None
        ]
        corpus[f"mean_pass@{k}"] = round(statistics.fmean(vals), 6) if vals else None

    modes: dict[str, int] = {}
    for s in summaries:
        for mode, n in s.failure_breakdown().items():
            modes[mode] = modes.get(mode, 0) + n

    spend = [s.usage() for s in summaries]
    measured = [u for u in spend if u.get("measured_attempts")]
    corpus["total_cost_usd"] = round(sum(u["total_cost_usd"] for u in measured), 6) if measured else None
    corpus["total_input_tokens"] = sum(u["total_input_tokens"] for u in measured) if measured else None
    corpus["total_output_tokens"] = sum(u["total_output_tokens"] for u in measured) if measured else None

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": corpus,
        "failure_modes": dict(sorted(modes.items(), key=lambda kv: -kv[1])),
        "inadmissible": [
            {"task": s.task_name, "problems": s.validity()["problems"]}
            for s in summaries
            if not s.validity()["admissible"]
        ],
        "tasks": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    return out
