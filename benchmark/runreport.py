"""Per-run report.json and per-model pass_summary.json.

Ported from mcp-stump. Two scores, deliberately never mixed:

  test_weights_percentage    deterministic. Weighted key-paths, no LLM.
  rubric_weights_percentage  judged. Requires a rubric authored with the task;
                             absent means null, not zero (zero would claim the
                             agent failed criteria that were never evaluated).

`final_reward` is the mean of the two -- a *reporting* number only. `reward` in
reward.json stays the binary terminal gate, because pass@k needs a yes/no and a
fractional reward turns every run into a partial pass.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


def _pct(x: float | None) -> float | None:
    return None if x is None else round(x * 100.0, 2)


@dataclass
class TestEntry:
    name: str
    weight: float
    passed: bool

    def as_dict(self) -> dict:
        return {"name": self.name, "weight": self.weight, "passed": self.passed}


@dataclass
class RubricEntry:
    number: str
    criterion: str
    type: str
    evaluation_target: str
    importance: str
    score: float
    is_positive: bool
    passed: bool
    justification: str = ""

    @classmethod
    def from_criterion(cls, c: dict, passed: bool, justification: str) -> "RubricEntry":
        return cls(
            number=c.get("number", "?"),
            criterion=c.get("criterion", ""),
            type=c.get("type", ""),
            evaluation_target=c.get("evaluation_target", "final_answer"),
            importance=c.get("importance", "important"),
            score=float(c.get("score", 1)),
            is_positive=bool(c.get("is_positive", True)),
            passed=passed,
            justification=justification,
        )

    def as_dict(self) -> dict:
        return {
            "number": self.number, "criterion": self.criterion, "type": self.type,
            "evaluation_target": self.evaluation_target, "importance": self.importance,
            "score": self.score, "is_positive": self.is_positive,
            "passed": self.passed, "justification": self.justification,
        }


def weighted_percentage(items: Sequence[tuple[float, bool]]) -> float | None:
    """(earned - penalty) / possible, over (weight, passed) pairs.

    A positive item earns its weight when it passes. A negative item is a thing
    that should NOT be true, so it deducts when it *does* hold -- which is how
    hallucination and collateral damage get priced.
    """
    pos_total = sum(w for w, _ in items if w > 0)
    if pos_total <= 0:
        return None
    earned = sum(w for w, ok in items if w > 0 and ok)
    penalty = sum(abs(w) for w, ok in items if w < 0 and ok)
    return (earned - penalty) / pos_total


@dataclass
class RunReport:
    model: str
    run_index: int
    tests: list[TestEntry] = field(default_factory=list)
    rubric: list[RubricEntry] = field(default_factory=list)
    exit_code: int = 0
    include_multimodal: bool = False

    @staticmethod
    def _ok(t: TestEntry) -> bool:
        """Is this entry in a good state? Goals pass; guards must NOT hold."""
        return (not t.passed) if t.weight < 0 else t.passed

    @property
    def test_score(self) -> float | None:
        return weighted_percentage([(t.weight, t.passed) for t in self.tests])

    @property
    def rubric_score(self) -> float | None:
        """(earned - penalty) / possible, over the POSITIVE criteria only.

        `score` is always a positive magnitude; `is_positive` carries the
        polarity. Feeding the raw score in would put negative criteria into the
        denominator, so a run that satisfied every positive criterion and
        committed no defect would score below 1.0.
        """
        if not self.rubric:
            return None
        return weighted_percentage([
            (r.score if r.is_positive else -abs(r.score), r.passed)
            for r in self.rubric])

    @property
    def final_reward(self) -> float:
        parts = [s for s in (self.test_score, self.rubric_score) if s is not None]
        return round(statistics.fmean(parts), 4) if parts else 0.0

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "run_index": self.run_index,
            "include_multimodal": self.include_multimodal,
            "pytest": {
                # Counted by OUTCOME, not by the raw flag: a guard doing its job
                # carries passed=False, and counting that as a failure would
                # report successes as failures.
                "passed": sum(1 for t in self.tests if self._ok(t)),
                "failed": sum(1 for t in self.tests if not self._ok(t)),
                "exit_code": self.exit_code,
                "reward": round(self.test_score, 6) if self.test_score is not None else 0.0,
                "tests": [t.as_dict() for t in sorted(self.tests, key=lambda x: x.name)],
            },
            "rubric": [r.as_dict() for r in self.rubric],
            "final_reward": self.final_reward,
            "test_weights_percentage": _pct(self.test_score),
            "rubric_weights_percentage": _pct(self.rubric_score),
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2))
        return path


def from_judge(model: str, run_index: int, judge_detail: dict, *,
               rubric: list[RubricEntry] | None = None,
               exit_code: int = 0, top_n: int = 40) -> RunReport:
    """Build a run report from the judge's per-key outcomes.

    Failures are kept in full; passing keys are truncated to `top_n` and the
    omitted ones folded into one aggregate entry carrying their summed weight,
    so `test_weights_percentage` equals the judge's `weighted_score` whatever
    `top_n` is.
    """
    outcomes: list[TestEntry] = []
    for o in judge_detail.get("failed_positive", []):
        outcomes.append(TestEntry(_name(o, "reached"), float(o.get("weight", 1.0)), False))
    for o in judge_detail.get("damaged_negative", []):
        outcomes.append(TestEntry(_name(o, "untouched"), -abs(float(o.get("weight", 1.0))), True))

    # Guards that HELD -- negative weight with passed=False is arithmetically
    # inert but adds visibility.
    for o in judge_detail.get("held_negative", []):
        outcomes.append(TestEntry(_name(o, "untouched"),
                                  -abs(float(o.get("weight", 1.0))), False))

    room = max(0, top_n - len(outcomes))
    passing = judge_detail.get("passed_positive", [])
    for o in passing[:room]:
        outcomes.append(TestEntry(_name(o, "reached"), float(o.get("weight", 1.0)), True))

    hidden = passing[room:]
    if hidden:
        outcomes.append(TestEntry(
            f"reached[+{len(hidden)}_more_passing]",
            round(sum(float(o.get("weight", 1.0)) for o in hidden), 6), True))

    return RunReport(model=model, run_index=run_index, tests=outcomes,
                     rubric=list(rubric or []), exit_code=exit_code)


def _name(outcome: dict, kind: str) -> str:
    return f"{kind}[{'.'.join(str(p) for p in outcome.get('path', []))}]"


# --------------------------------------------------------------------------
# per-model roll-up
# --------------------------------------------------------------------------

def pass_summary(model: str, reports: Sequence[RunReport]) -> dict:
    tests = [r.test_score for r in reports if r.test_score is not None]
    rubs = [r.rubric_score for r in reports if r.rubric_score is not None]
    return {
        "model": model,
        "runs": len(reports),
        "average_test_weights_percentage": _pct(statistics.fmean(tests)) if tests else None,
        "average_rubric_weights_percentage": _pct(statistics.fmean(rubs)) if rubs else None,
        "per_run": [
            {
                "run_index": r.run_index,
                "include_multimodal": r.include_multimodal,
                "test_weights_percentage": _pct(r.test_score),
                "rubric_weights_percentage": _pct(r.rubric_score),
            }
            for r in reports
        ],
    }


def write_pass_summary(model: str, reports: Sequence[RunReport], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pass_summary(model, reports), indent=2))
    return path


def rubric_entries_from_result(rubric_result: dict | None) -> list[RubricEntry]:
    """Adapt a benchmark.rubric_judge / rubric_pytest_judge result into RubricEntry list.

    Accepts either the mcp-stump-style `per_criterion` list (each carrying
    `satisfied`, `score`, `is_positive`) or the dict-rubric `per_check` list.
    Absent/empty -> [] so `rubric_score` stays null.
    """
    if not rubric_result:
        return []
    out: list[RubricEntry] = []
    for c in rubric_result.get("per_criterion") or []:
        out.append(RubricEntry.from_criterion(
            c, bool(c.get("satisfied")), c.get("justification", "")))
    return out


def load_rubric(task_dir: Path) -> list[dict]:
    """rubric.json is an INPUT, authored alongside the task. Absent is fine."""
    f = task_dir / "rubric.json"
    if not f.is_file():
        return []
    data = json.loads(f.read_text())
    return data if isinstance(data, list) else data.get("criteria", [])
