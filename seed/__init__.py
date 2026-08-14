"""Task-authoring pipeline (front end).

Implements the four-stage flow from PIPELINE_IMPLEMENTATION_PLAN.md:

    ① SEED    seed.py   pick a unique (apps, seed, level, levers, fixture)
                        combination, dedup via the registry, bake old_env,
                        emit a bundle skeleton to tasks/<slug>/
    ② HANDOFF backup.py snapshot the emitted bundle to tasks_backup/<slug>/
    ③ AUTHOR  finish.py bake gt_env from the authored oracle, run the lint
                        gates (lint_bundle + lint_rubric via validate_task)
    ④ RUN     (existing run_benchmark.py — unchanged)

Nothing in this package mutates the runtime, graders, or sandbox apps. It only
reuses them: benchmark.bake_state_mcp (world baker) and benchmark.validate_task
(the authoring gate this package extends).
"""
