"""AUTHOR finish — plan §5 (finish.py), Stage ③ "tasker-finish".

After the tasker authors instruction.md + tests/oracle.json + rubric/pytest/
gold_plan, this bakes tests/gt_env.json by EXECUTING the oracle against the
seeded world (benchmark.bake_state_mcp.bake), then runs the full authoring gate
(benchmark.validate_task.validate — including the lint_bundle + lint_rubric
checks this package registers). Exit non-zero on any problem so it can gate CI.

    python -m seed.finish <slug|task_dir>
"""

from __future__ import annotations

import os
import sys

from seed.lint_bundle import resolve_task_dir

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def finish(task_dir: str) -> dict:
    """Bake gt_env then validate. Returns the validate() report (with a
    'bake' key describing the bake outcome)."""
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from benchmark.bake_state_mcp import bake
    from benchmark.validate_task import validate

    from seed.lint_bundle import bundle_complete
    from seed.lint_rubric import rubric_trace

    bake_note = {}
    try:
        old, gt = bake(task_dir, repo_root=_ROOT, write=True)
        bake_note = {"ok": True, "note": "gt_env baked from oracle"}
    except SystemExit as exc:
        bake_note = {"ok": False, "note": str(exc)}

    # validate() = the shared authoring gate (gold_plan / gt / traj_tests).
    report = validate(task_dir)
    # Pipeline-specific lints (kept out of the shared gate so legacy bundles are
    # unaffected — see benchmark/validate_task.py note and BUNDLE_SCHEMA.md).
    report["checks"]["bundle_complete"] = bundle_complete(task_dir)
    report["checks"]["rubric_trace"] = rubric_trace(task_dir)
    report["bake"] = bake_note

    extra = report["checks"]["bundle_complete"] + report["checks"]["rubric_trace"]
    report["problems"] = report.get("problems", []) + extra
    if not bake_note["ok"]:
        report["problems"] = ["gt_env bake failed: " + bake_note["note"]] + \
            report["problems"]
    report["ok"] = not report["problems"]
    return report


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        raise SystemExit("usage: python -m seed.finish <slug|task_dir>")
    task_dir = resolve_task_dir(argv[0])
    rep = finish(task_dir)
    mark = "PASS" if rep["ok"] else "FAIL"
    print(f"[{mark}] {rep['task']}  (bake: {rep['bake']['note']})")
    for p in rep.get("problems", []):
        print(f"  - {p}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
