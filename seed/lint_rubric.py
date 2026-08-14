"""Rubric-vs-data trace — plan §5 (lint_rubric.py), §9 invariant 3, §13.3 G5.

Enforces "rubrics never introduce new data": every DATA literal a rubric
criterion names (entity ids, dashed ids, large numbers) must trace back to the
task's mock data — tests/old_env.json, tests/gt_env.json, or tests/oracle.json.
A criterion that references an entity the seeded world doesn't contain is an
authoring bug that would grade against a fiction.

Scope is deliberately narrow to avoid false positives on natural-language
criteria: only literals that LOOK like data (snake_case ids like
`item_plain_tent`, dashed ids like `conv-1001`, integers >= 100) are traced.
Ordinary English ("user-facing", "one-line") is not a data literal.

Escape hatch: a rubric may carry a top-level `_lint_ignore: [ "<literal>", ... ]`
allow-list, and any criterion object with `"lint_ignore": true` is skipped.

Entry points:
  * rubric_trace(task_dir) -> [problems]      registered into
    benchmark.validate_task._CHECKS.
  * python -m seed.lint_rubric <slug|dir>      standalone CLI, exit 1 on any miss.
"""

from __future__ import annotations

import json
import os
import re
import sys

from seed.lint_bundle import resolve_task_dir

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# A "data literal": snake_case id (has an underscore), or a dashed id carrying a
# digit (conv-1001), or a standalone integer with >= 3 digits.
_ID_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_ID_DASH = re.compile(r"\b[a-z]+-\d+\b", re.IGNORECASE)
_INT_BIG = re.compile(r"(?<![\w.])\d{3,}(?:\.\d+)?(?![\w.])")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _corpus(task_dir: str) -> str:
    """One lowercased blob of every string/number leaf in the mock data."""
    parts = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, bool):
            pass
        elif isinstance(x, (int, float)):
            parts.append(str(x))
        elif isinstance(x, str):
            parts.append(x)

    for rel in ("tests/old_env.json", "tests/gt_env.json", "tests/oracle.json"):
        data = _load_json(os.path.join(task_dir, rel))
        if data is not None:
            walk(data)
    return "\n".join(parts).lower()


def _literals(text: str) -> set:
    out = set()
    for rx in (_ID_SNAKE, _ID_DASH, _INT_BIG):
        for m in rx.findall(text):
            out.add(str(m).lower())
    return out


def _criterion_strings(rubric) -> list:
    """The tasker-authored text fields, and the per-criterion ignore flags."""
    items = []
    if isinstance(rubric, dict):
        crits = rubric.get("criteria", [])
    elif isinstance(rubric, list):
        crits = rubric
    else:
        crits = []
    for c in crits:
        if isinstance(c, dict):
            if c.get("lint_ignore"):
                continue
            text = " ".join(str(c.get(k, "")) for k in
                            ("criterion", "check", "description", "note"))
            items.append(text)
        elif isinstance(c, str):
            items.append(c)
    return items


def rubric_trace(task_dir: str) -> list:
    rubric_path = os.path.join(task_dir, "tests", "rubric.json")
    if not os.path.exists(rubric_path):
        rubric_path = os.path.join(task_dir, "rubric.json")
    rubric = _load_json(rubric_path)
    if rubric is None:
        return []                                    # no rubric -> nothing to trace

    ignore = set(str(x).lower() for x in
                 (rubric.get("_lint_ignore", []) if isinstance(rubric, dict) else []))
    blob = _corpus(task_dir)
    if not blob:
        return ["cannot trace rubric literals: no old_env/gt_env/oracle data baked yet"]

    problems = []
    seen = set()
    for text in _criterion_strings(rubric):
        for lit in _literals(text):
            if lit in ignore or lit in seen:
                continue
            seen.add(lit)
            if lit not in blob:
                problems.append(
                    f"rubric references data literal '{lit}' absent from "
                    f"old_env/gt_env/oracle (invented entity? add to _lint_ignore "
                    f"if intentional)")
    return problems


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        raise SystemExit("usage: python -m seed.lint_rubric <slug|task_dir>")
    task_dir = resolve_task_dir(argv[0])
    problems = rubric_trace(task_dir)
    slug = os.path.basename(task_dir.rstrip("/"))
    if problems:
        print(f"[FAIL] {slug}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"[PASS] {slug} — rubric literals trace to mock data")
    return 0


if __name__ == "__main__":
    sys.exit(main())
