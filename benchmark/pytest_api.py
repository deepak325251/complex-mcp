"""Authored pytest checks — the task's grading surface.

Replaces auto-derived key-path specs. An authored check states one intent, in
Python, with a name a human wrote:

    @weight(3.0)
    def test_every_position_closed(final_state):
        assert at(final_state, "LightStock.output.portfolio") == []

    @protects
    def test_watchlist_untouched(initial_state, final_state):
        assert_unchanged(initial_state, final_state, "LightStock.output.watch_list")

Scoring:
    Rc  weighted pass rate over goal checks       (completion)
    Rb  weighted fail rate over @protects checks  (misbehaviour)
    reward = 1.0 iff every goal passed and no protection was broken

reward stays binary because pass@k needs yes/no; weighted_score rides alongside
for RL shaping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

MISSING = object()


def weight(value: float) -> Callable:
    def deco(fn: Callable) -> Callable:
        fn._stump_weight = float(value)
        return fn
    return deco


def protects(fn: Callable) -> Callable:
    fn._stump_protects = True
    return fn


def at(state: dict, dotted: str, default: Any = MISSING) -> Any:
    cur: Any = state
    for seg in dotted.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(seg)]
                continue
            except (ValueError, IndexError):
                if default is MISSING:
                    raise AssertionError(f"no such path: {dotted} (at {seg!r})") from None
                return default
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
            continue
        if default is MISSING:
            raise AssertionError(f"no such path: {dotted} (at {seg!r})")
        return default
    return cur


def assert_unchanged(before: dict, after: dict, dotted: str) -> None:
    b = at(before, dotted, None)
    a = at(after, dotted, None)
    assert a == b, (
        f"{dotted} changed\n"
        f"  before: {json.dumps(b, default=str)[:300]}\n"
        f"  after : {json.dumps(a, default=str)[:300]}"
    )


def called(trace: Iterable[dict], tool: str) -> bool:
    return any(str(r.get("tool", "")).split("::")[-1] == tool for r in trace)


def no_writes(trace: Iterable[dict], write_tools: Iterable[str]) -> None:
    hit = sorted({str(r.get("tool", "")).split("::")[-1] for r in trace}
                 & set(write_tools))
    assert not hit, f"expected no state-changing calls, got: {', '.join(hit)}"


@dataclass
class CheckOutcome:
    name: str
    weight: float
    passed: bool
    protects: bool
    message: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "weight": self.weight,
            "passed": self.passed,
            "protects": self.protects,
            "message": self.message[:2000],
        }


@dataclass
class CheckReport:
    outcomes: list[CheckOutcome] = field(default_factory=list)

    @property
    def goals(self) -> list[CheckOutcome]:
        return [o for o in self.outcomes if not o.protects]

    @property
    def guards(self) -> list[CheckOutcome]:
        return [o for o in self.outcomes if o.protects]

    @property
    def completion_rate(self) -> float:
        total = sum(o.weight for o in self.goals)
        if total <= 0:
            return 1.0
        return sum(o.weight for o in self.goals if o.passed) / total

    @property
    def misbehaving_rate(self) -> float:
        total = sum(o.weight for o in self.guards)
        if total <= 0:
            return 0.0
        return sum(o.weight for o in self.guards if not o.passed) / total

    @property
    def weighted_score(self) -> float:
        earned = sum(o.weight for o in self.goals if o.passed)
        total = sum(o.weight for o in self.goals)
        penalty = sum(o.weight for o in self.guards if not o.passed)
        if total <= 0:
            return 1.0 if self.passed else 0.0
        return max(0.0, (earned - penalty) / total)

    @property
    def total(self) -> int:
        return len(self.goals)

    @property
    def recall(self) -> int:
        return sum(1 for o in self.goals if o.passed)

    @property
    def misbehave(self) -> int:
        return sum(1 for o in self.guards if not o.passed)

    @property
    def passed(self) -> bool:
        return (
            all(o.passed for o in self.goals)
            and all(o.passed for o in self.guards)
            and bool(self.goals)
        )

    @property
    def reward(self) -> float:
        return 1.0 if self.passed else 0.0

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reward": self.reward,
            "total": len(self.goals),
            "recall": sum(1 for o in self.goals if o.passed),
            "misbehave": sum(1 for o in self.guards if not o.passed),
            "completion_rate": round(self.completion_rate, 6),
            "misbehaving_rate": round(self.misbehaving_rate, 6),
            "weighted_score": round(self.weighted_score, 6),
            "checks": [o.as_dict() for o in self.outcomes],
            "failed_goals": [o.as_dict() for o in self.goals if not o.passed],
            "broken_guards": [o.as_dict() for o in self.guards if not o.passed],
            "weights": {
                "positive_total": round(sum(o.weight for o in self.goals), 6),
                "positive_earned": round(
                    sum(o.weight for o in self.goals if o.passed), 6),
                "negative_penalty": round(
                    sum(o.weight for o in self.guards if not o.passed), 6),
            },
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2))
        return path

    @classmethod
    def load(cls, path: Path) -> "CheckReport":
        d = json.loads(Path(path).read_text())
        return cls(outcomes=[
            CheckOutcome(
                name=c["name"],
                weight=float(c.get("weight", 1.0)),
                passed=bool(c["passed"]),
                protects=bool(c.get("protects")),
                message=c.get("message", ""),
            )
            for c in d.get("checks", [])
        ])


def run_checks(module, initial_state: dict, final_state: dict, trace: list[dict] | None = None) -> CheckReport:
    """Run all test_* callables in module and collect outcomes.

    Each check may accept any subset of (initial_state, final_state, trace) as
    kwargs. Weight defaults to 1.0; @protects marks a guard (misbehaviour).
    """
    import inspect
    trace = trace or []
    report = CheckReport()
    for name in dir(module):
        if not name.startswith("test_"):
            continue
        fn = getattr(module, name)
        if not callable(fn):
            continue
        w = float(getattr(fn, "_stump_weight", 1.0))
        is_guard = bool(getattr(fn, "_stump_protects", False))
        sig = inspect.signature(fn)
        kwargs = {}
        if "initial_state" in sig.parameters:
            kwargs["initial_state"] = initial_state
        if "final_state" in sig.parameters:
            kwargs["final_state"] = final_state
        if "trace" in sig.parameters:
            kwargs["trace"] = trace
        try:
            fn(**kwargs)
            report.outcomes.append(CheckOutcome(name=name, weight=w, passed=True, protects=is_guard))
        except AssertionError as exc:
            report.outcomes.append(CheckOutcome(
                name=name, weight=w, passed=False, protects=is_guard, message=str(exc)))
        except Exception as exc:
            report.outcomes.append(CheckOutcome(
                name=name, weight=w, passed=False, protects=is_guard,
                message=f"{type(exc).__name__}: {exc}"))
    return report


def load_checks_from_file(path: Path):
    """Import a task's checks.py file and return the module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_task_checks", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load checks from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
