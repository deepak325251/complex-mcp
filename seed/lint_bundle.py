"""Bundle-completeness gate — plan §5 (lint_bundle.py), §9 invariant 4, §13.3 G4.

Asserts a bundle carries every file the runtime needs (per seed/BUNDLE_SCHEMA.md)
so the runtime never silently drops a half-built task. Also checks the canary
GUID is present in task.toml + instruction.md (§9 invariant 5) and the machine-
authoritative [task.metadata] keys exist.

Two entry points:
  * bundle_complete(task_dir) -> [problems]   registered into
    benchmark.validate_task._CHECKS so `validate_task` runs it too.
  * python -m seed.lint_bundle <slug|dir>      standalone CLI, exit 1 on any miss.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# Files a bundle MUST carry to be gradeable in-process (weighted/graph/pytest).
# This is the family-agnostic core: it holds for both the complexmcp-native
# bundles this pipeline emits and the mcp-stump-family bundles authored
# elsewhere. The Docker state-diff path files (verify.py/test.sh/gen_gt.py/
# GT_GENERATION.md, environment/Dockerfile) are recommended for harbor parity
# but NOT required — the in-process graders never read them.
REQUIRED = [
    "task.toml",
    "instruction.md",
    "environment/docker-compose.yaml",
    "tests/oracle.json",
    "tests/old_env.json",
    "tests/gt_env.json",
    "tests/gold_plan.json",
    "tests/efs.json",
    "tests/rubric.json",
    "tests/test_outputs.py",
    "tests/test_weights.json",
    "solution/solve.sh",
    "solution/trajectory.json",
]

# Present in harbor-parity bundles; their absence is reported as a note, not a
# failure (the in-process grading path does not use them).
RECOMMENDED = [
    "environment/Dockerfile",
    "tests/verify.py",
    "tests/test.sh",
    "tests/gen_gt.py",
    "tests/GT_GENERATION.md",
]


def resolve_task_dir(arg: str) -> str:
    """Accept a bundle path or a bare slug (resolved under tasks/)."""
    if os.path.isdir(arg) and os.path.exists(os.path.join(arg, "task.toml")):
        return arg
    cand = os.path.join(_ROOT, "tasks", arg)
    if os.path.isdir(cand):
        return cand
    return arg


def bundle_complete(task_dir: str) -> list:
    problems = []

    for rel in REQUIRED:
        if not os.path.exists(os.path.join(task_dir, rel)):
            problems.append(f"missing required file: {rel}")

    toml_path = os.path.join(task_dir, "task.toml")
    if os.path.exists(toml_path):
        import tomllib
        try:
            with open(toml_path, "rb") as fh:
                doc = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            return problems + [f"task.toml is not valid TOML: {exc}"]
        if str(doc.get("schema_version")) != "1.0":
            problems.append('task.toml schema_version != "1.0"')
        meta = doc.get("task", {}).get("metadata", {})
        for key in ("seed", "apps"):
            if meta.get(key) is None:
                problems.append(f"task.toml [task.metadata].{key} missing")
        # Difficulty may be encoded as an integer `level` (complexmcp-native)
        # or a `capability_level` label (mcp-stump family) — either satisfies it.
        if meta.get("level") is None and meta.get("capability_level") is None:
            problems.append("task.toml [task.metadata] has neither level nor "
                            "capability_level")
        # The canary lives in the "# harbor-canary GUID <guid>" banner comment
        # (both families). The separate [task.metadata].canary_guid key is a
        # bonus our emitter adds but is not required.
        import re
        raw = open(toml_path, encoding="utf-8").read()
        m = re.search(r"harbor-canary GUID\s+([0-9a-fA-F-]{8,})", raw)
        if not m:
            problems.append("task.toml missing harbor-canary GUID")
        else:
            guid = m.group(1)
            instr = os.path.join(task_dir, "instruction.md")
            if os.path.exists(instr):
                itext = open(instr, encoding="utf-8").read()
                if "harbor-canary" not in itext:
                    problems.append("instruction.md missing harbor-canary canary comment")
                elif guid not in itext:
                    problems.append("instruction.md canary GUID does not match task.toml")

    return problems


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        raise SystemExit("usage: python -m seed.lint_bundle <slug|task_dir>")
    task_dir = resolve_task_dir(argv[0])
    problems = bundle_complete(task_dir)
    notes = [f"recommended (harbor-parity) file absent: {rel}"
             for rel in RECOMMENDED
             if not os.path.exists(os.path.join(task_dir, rel))]
    slug = os.path.basename(task_dir.rstrip("/"))
    if problems:
        print(f"[FAIL] {slug}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"[PASS] {slug} — complete bundle")
    for n in notes:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
