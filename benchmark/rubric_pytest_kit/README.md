# ComplexMCP Rubric + Pytest Kit

A general, reusable grading layer for **ComplexMCP harbour tasks**. It replaces the binary
state-diff verifier (`tests/verify.py` + `gt_env.json`) with a **Skoll-style two-channel grader**:

- **Channel A — weighted pytest** against the world-state **dump** (`$DUMP_URL` / `old_env.json`).
- **Channel B — LLM-judged rubric** against the agent deliverable (`output.md`).

It reads the *same* seeded world state the old verifier dumped, but grades granularly (per-mutation
weights, `{-5,-3,-1,1,3,5}`) instead of one all-or-nothing `Rc==1 & Rb==0`.

## Files

```
_rubric_pytest_kit/
├── README.md                 ← you are here
├── GENERATOR.md              ← authoring rules reference (channels, weight scale, real dump schema, forbidden patterns)
├── grade.py                  ← the grader (pytest weighted score + rubric verdicts → reward.json)
├── test.sh                   ← harbor entrypoint (replaces the old state-diff test.sh)
├── templates/
│   ├── test_outputs.py       ← Channel-A header (dump accessors) + example flat tests
│   ├── test_weights.json     ← one weight per test
│   └── rubric.json           ← Channel-B criteria (7-field schema, wrapped in {"criteria":[...]})
└── qc/
    ├── no_class_check.py     ← test_outputs.py must be flat test_ functions, 0 classes
    └── channel_check.py      ← pytest reads only dump+baseline; Convention-B polarity; no subjective adjectives
```

## Grading model

Channel A (pytest):

    A = max(0, (Σ passed-positive-weight − Σ |triggered-negative-weight|) / Σ all-positive-weight)

A FAILED test contributes 0 (both signs) — a crashed/no-op agent cannot dodge a penalty, and cannot
bank credit for a file that merely exists. Channel B (rubric) uses the same formula over criterion
scores. `reward = 1 iff A ≥ A_THRESHOLD (default 1.0) and (B is null or B ≥ B_THRESHOLD (default 0.7))`.
`reward.json` also reports the continuous `pytest_score` / `rubric_score`.

## Instantiate the kit for a task

The pytest + rubric are part of the input bundle — **the task author writes them by hand** (Skoll
manual-kit style).

1. Scaffold the three files into the task's `tests/` (the correct accessor header is pre-filled):
   ```
   scripts/init_task_tests.sh harbour-task/<task>
   ```
2. Edit them for your task:
   - `tests/test_outputs.py` — BELOW the `# EXAMPLE TESTS` marker, write flat `def test_*()` functions
     using the provided accessors (`dump`, `old_env`, `app`, `collection`, `find`, `count`, `added`).
     **Do NOT edit the header** — it is correct-by-construction (unwraps the `{status,output}` dump
     envelope, reads `$NEW_ENV`). See `GENERATOR.md` for the rules (channel separation, weight scale,
     real dump schema — no `my_balance` — and the forbidden `assert` patterns).
   - `tests/test_weights.json` — one weight per test, `{-5,-3,-1,1,3,5}`.
   - `tests/rubric.json` — Channel-B criteria (7-field schema).
   Worked reference: `harbour-task/complexmcp-l2-s0-buy-3kg-of-honeycrisp-apples-*/tests/`.

3. QC before shipping (below), then `run_benchmark.py` grades from the task's `tests/` automatically.
   `grade.py` + `test.sh` are only for standalone/docker grading via `$DUMP_URL` — not the benchmark.

3. QC before shipping:
   ```bash
   python3 qc/no_class_check.py  <task>/tests/test_outputs.py
   python3 qc/channel_check.py   <task>/tests/test_outputs.py
   python3 -c "import json;json.load(open('<task>/tests/rubric.json'));json.load(open('<task>/tests/test_weights.json'))"
   ```
   Every test in `test_weights.json` must have a matching `def test_*` and vice-versa.

## Run the grader

```bash
# apps must be up and exposing $DUMP_URL (docker/ compose or start_softwares.sh)
DUMP_URL=http://localhost:8900/__dump__ \
OLD_ENV=<task>/tests/old_env.json \
VERIFIER_LOG_DIR=/logs/verifier \
bash <task>/tests/test.sh
# -> /logs/verifier/reward.json  {reward, pytest_score, rubric_score, ...}
```

## Channel B — producing rubric verdicts

`grade.py` reads `rubric_verdicts.json` (`{"R1": true, ...}`) — one boolean per criterion, "did the
described text occur in `output.md`?". Generate it by pasting each criterion + `output.md` into a
judge model session, or wire your harness's judge into `test.sh` step 2. Without the file, only
Channel A is graded (and `rubric_score` is reported as `null`).

## Requirements

`pip install pytest` (grade.py drives pytest in-process). Everything else is stdlib.
