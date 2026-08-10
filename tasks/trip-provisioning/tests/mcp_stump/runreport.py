"""Per-run report.json and per-model pass_summary.json.

Schema follows the WildClaw bench reference so bundles are readable by the same
tooling:

    report.json
      { model, run_index, include_multimodal,
        pytest: { passed, failed, exit_code, reward, tests: [{name, weight, passed}] },
        rubric: [{ number, criterion, type, evaluation_target, importance,
                   score, is_positive, passed, justification }],
        final_reward, test_weights_percentage, rubric_weights_percentage }

    pass_summary.json
      { model, runs, average_test_weights_percentage,
        average_rubric_weights_percentage, per_run: [...] }

Two scores, deliberately never mixed:

  test_weights_percentage    deterministic. Weighted key-paths, no LLM.
  rubric_weights_percentage  judged. Requires a rubric.json authored with the
                             task; absent means null, not zero.

`final_reward` is their mean of the two. It is a *reporting* number only --
`reward` in reward.json stays the binary terminal gate, because pass@k needs a
yes/no and a fractional reward turns every run into a partial pass.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


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

    # -- derived -----------------------------------------------------------

    @staticmethod
    def _ok(t: TestEntry) -> bool:
        """Is this entry in a good state? Goals pass; guards must NOT hold."""
        return (not t.passed) if t.weight < 0 else t.passed

    @property
    def test_score(self) -> float | None:
        return weighted_percentage([(t.weight, t.passed) for t in self.tests])

    @property
    def rubric_score(self) -> float | None:
        if not self.rubric:
            return None
        # A negative criterion is scored on whether the bad thing HELD, so its
        # contribution is keyed off `passed` meaning "the criterion is true of
        # the output", matching the reference.
        return weighted_percentage([(r.score, r.passed) for r in self.rubric])

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
                # Counted by OUTCOME, not by the raw flag. For a guard, weight
                # is negative and `passed` means "the forbidden thing held" --
                # so a guard doing its job carries passed=False, and counting
                # that as a failure reports five successes as five failures.
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

    Key-paths are the tests. Reporting all 359 would drown the file, so failures
    are kept in full and passes are truncated -- a report that hides a failure
    would be worse than useless, one that hides a pass is merely shorter.

    Truncation must not change the score. Omitted passing keys are folded into
    one aggregate entry carrying their summed weight, so
    `test_weights_percentage` equals the judge's `weighted_score` whatever
    `top_n` is. An earlier version synthesised placeholder passes at weight 1.0;
    with group-balanced weights (real keys ~0.05) the placeholders carried ~99%
    of the total and a failed sub-goal reported as 99.6% instead of 85%.
    """
    outcomes = []
    for o in judge_detail.get("failed_positive", []):
        outcomes.append(TestEntry(_name(o, "reached"), float(o.get("weight", 1.0)), False))
    for o in judge_detail.get("damaged_negative", []):
        outcomes.append(TestEntry(_name(o, "untouched"), -abs(float(o.get("weight", 1.0))), True))

    # Guards that HELD. Emitted at negative weight with passed=False, which is
    # arithmetically inert -- weighted_percentage counts w>0 for the total and
    # earned, and deducts only for w<0 that DID hold -- so this adds visibility
    # without moving the score by a hair.
    #
    # They were omitted entirely when guards meant 400 sampled key-paths and
    # listing them would have drowned the file. With authored guards there are
    # a handful and each is a deliberate claim; "the pre-existing cart item was
    # not discarded -- verified" is the kind of thing a reader needs.
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


def load_rubric(task_dir: Path) -> list[dict]:
    """rubric.json is an INPUT, authored alongside the task. Absent is fine."""
    f = task_dir / "rubric.json"
    if not f.is_file():
        return []
    data = json.loads(f.read_text())
    return data if isinstance(data, list) else data.get("criteria", [])
