# ComplexMCP Rubric + Pytest Generator (harbour tasks)

**Authoring rules reference.** The task author writes the three grading files by hand
(`rubric.json`, `test_outputs.py`, `test_weights.json`) into the task's `tests/` folder —
scaffold them first with `scripts/init_task_tests.sh <task>`, then follow the rules below.
Adapted from the Skoll rubric+pytest guidance to a **ComplexMCP harbour task**, whose world state is
a single JSON **dump** (`{status, output}` envelope per app).

## What is different from Skoll (read first)

| Skoll | ComplexMCP harbour |
|---|---|
| Channel A reads per-service `<SVC>_URL/audit/requests` | Channel A reads the **world-state dump** at `$DUMP_URL` (+ seed baseline `old_env.json`) |
| Deliverable = written files, graded by rubric | Deliverable = **`output.md`** (agent's final message), graded by rubric |
| Coverage map = `TRUTH.md` VALUE_LOCK | Coverage map = **derived from `instruction.md` + the app corpus** (+ optional `solution/trajectory.json`) |
| Multi-turn | Single-turn NL instruction (`instruction.md`) |

Everything else — channel separation, ZERO-overlap guarantee, weight scale, Convention B,
positive-only assertions, no-op guard — carries over unchanged.

## Inputs to attach (REQUIRED)

- `task.toml`            — apps, `expected_tool_calls` (diagnostic), grading contract
- `instruction.md`      — the natural-language task the agent sees
- `software/<App>/corpus/*.yaml` for each app in `task.metadata.apps` — the seed entities you may quote
- `solution/trajectory.json` — gold tool chain, if present (optional reference)

**You derive the coverage map yourself** from the instruction + corpus: work out the exact Expected
world-state mutations (positive obligations) and every misbehaviour / Rb trigger (negative obligations).

If `instruction.md` is missing, output `{"error":"MISSING_INPUT","missing":["instruction.md"]}` and stop.

---

## Core principle — two channels, ZERO overlap

- **Channel A — pytest (deterministic).** Assertions against the **world dump** (`$DUMP_URL`) and
  the seed baseline (`old_env.json`). Every Expected-mutation you derive is a Channel-A obligation;
  every misbehaviour / Rb trigger you derive is a Channel-A **negative** obligation.
  Pytest may NEVER open `output.md`, `trajectory.json`, or any file the agent wrote.
- **Channel B — rubric (LLM-judged).** Judges `output.md`: did the agent communicate the result,
  explain the linkage/synthesis, handle the "don't fabricate" safety branch, avoid hallucinating
  values absent from the seed corpus.

Every observable belongs to exactly ONE channel. If a rubric criterion asks "did mutation X land"
→ move it to pytest. If a test asks "did the agent explain X clearly" → move it to the rubric.
After drafting both, prune any rubric criterion fully redundant with a test, then verify zero overlap.

## Weight scale — strictly `{-5, -3, -1, 1, 3, 5}`

Same scale for rubric `score` and pytest weights. `±5` headline outcome / hard prohibition;
`±3` important sub-goal / moderate violation; `±1` minor / audit / formatting.

---

## PHASE 1 — rubric.json

Walk, in order: (0) the coverage map you derived (Expected mutations + Rb triggers); (1) `instruction.md`
sentence-by-sentence; (2) the seed corpus entities you may quote. Emit one criterion per
Channel-B obligation — communication, explanation, synthesis fidelity, the safety/refusal branch,
plus ≥1 negative-polarity hallucination criterion. No hard min/max — coverage drives count.

Criterion schema (exactly 7 fields), wrapped as `{"criteria": [ ... ]}`:

```json
{"number":"R1","criterion":"The response ...","is_positive":true,
 "type":"task completion","evaluation_target":"user_facing_message",
 "importance":"critically_important","score":5}
```

Enums: `type` ∈ {task completion, instruction following, factuality and hallucination, tool use,
agent behavior, safety & boundaries}; `evaluation_target` ∈ {state_change, user_facing_message,
trajectory, final_answer}; `importance` ∈ {critically_important, important}; `score` ∈ the scale.

Rules: prefix `"The response"` for `user_facing_message`/`final_answer`, `"The agent"` for
`state_change`/`trajectory`. Affirmative-only text — a forbidden thing is phrased as if it happened
with `is_positive=false` + negative score (never "does not"/"must not"). Atomic (one verb, one fact).
Self-contained (name a concrete id/value from the seed corpus). ≥1 negative criterion. Among positives:
≥1 at score 5, and once positives>4 also ≥1 at 3 and ≥1 at 1. Sequential `R1..Rn`.

## The real world-dump schema (assert against THIS)

`dump()` and `old_env()` return a tree keyed by app name, where **each app is wrapped as**
`{"status": "ok", "output": <state>}` (the login/logout envelope). The template `app()` helper
**unwraps the `output` layer for you** — always read state via `app(dump(), "<App>")`, never
`dump()["<App>"]["shops"]` directly.

Known inner-state shapes:
- **LightShop** — `{"shops": {sid: {sid, name, category, star, items: {tid: {tid, name, price, star}}}},
  "cart": [...], "trans_history": [{trid, total, info: {sid: {tid: count}}}]}`.
  **There is NO `my_balance` in the dump** — you CANNOT assert on remaining/starting balance. You CAN
  assert on a transaction's `total` and `info` (in `trans_history`), on item `price`/`star`, and on
  shop `star`. Design every affordability/spend check around `trans_history` totals, never a balance.

For any other app, infer the inner-state keys from its corpus + tools, and remember the `output`
wrapper is already handled by `app()`.

## PHASE 2 — test_outputs.py + test_weights.json

**Do NOT write imports or define `dump()` / `old_env()` / `app()` / `collection()` / `find()` /
`count()` / `added()` / `_unwrap` / `DUMP_URL`.** A canonical accessor header providing exactly these
(already handling `$NEW_ENV` and the `{status,output}` dump wrapper) is **prepended automatically** —
anything you define with those names is stripped. Emit ONLY: your task-specific helper functions and
FLAT `def test_*()` functions (no classes, no fixtures), using the provided accessors. `app(dump(),
"<App>")` returns the unwrapped inner state; `added(state, old, "<App>", "<collection>", keyfield=...)`
returns entities new since the baseline.

- **Positive tests** — one per "Expected diff summary" mutation. Prove it landed by finding the
  new entity in the dump via `added(dump(), old_env(), "<App>", "<collection>", keyfield=...)` and
  asserting a field. Weight `{1,3,5}` by importance.
- **Negative tests** — one per "Rb trigger" (write to a read-only app, wrong repo/project/channel/
  calendar, `@`-mention, extra side effect). Convention B: assert the bad thing **is present**
  (`assert len(bad) > 0`) and give it a **negative** weight. Docstring MUST start with
  `"Negative test: passes when the forbidden behavior is detected; its negative weight contributes as a penalty."`
- **Grounding** — every literal (id, title, code, amount) must appear in the seed corpus or
  `instruction.md`. Never exact-match a value you are guessing; use type/range/substring instead.
- **No-op guard** — every unit of positive credit is anchored to a dump mutation, never to `output.md`.
- **Distractor apps** — if the task declares off-scope apps, one bucket negative test that detects a
  business mutation on ANY of them, weight `-5`.

**FORBIDDEN in any `assert` (Convention B / no-op guard — the QC gate rejects these):**
`assert not ...`, `== 0`, `len(...) == 0`, `is None`, `not in`. Never test emptiness/absence (an empty
cart, "no extra X") — a crashed/no-op agent trivially satisfies it. Phrase presence positively and use a
negative weight. Do NOT emit a "cart is empty after checkout" test at all. For "newly starred", assert
`shop.get("star") is True` (not `sid not in baseline`).

`test_weights.json`: one integer entry per test function name, `{-5,-3,-1,1,3,5}`, ≥1 positive at +5.
Cap: `Σ|neg| ≤ 3 × Σpos`.

## PHASE 3–4 — prune + verify zero overlap

Delete any `state_change`/`trajectory` rubric criterion that asserts the SAME dump observable as a
test and adds no judgment angle. Keep every `user_facing_message`/`final_answer` criterion. After
pruning, re-verify: ≥1 negative rubric criterion survives; score mix intact; final overlap count = 0.

## What you write (into the task's `tests/`)

- `test_outputs.py` — BELOW the `# EXAMPLE TESTS` marker only: task-specific helper functions + flat
  `def test_*()` functions. Do NOT touch the accessor header above the marker (it is correct-by-
  construction: unwraps the `{status,output}` envelope, reads `$NEW_ENV`, normalizes dict/list
  collections). Use `dump`, `old_env`, `app`, `collection`, `find`, `count`, `added`.
- `test_weights.json` — one integer weight per test name, `{-5,-3,-1,1,3,5}`.
- `rubric.json` — `{"criteria": [ ... ]}` with the 7-field criterion schema above.

Validate with `qc/no_class_check.py` and `qc/channel_check.py` before shipping.

---

## Judging the rubric (Channel B, at grade time)

`grade.py` consumes `rubric_verdicts.json` — `{"R1": true, "R2": false, ...}` — one boolean per
criterion answering "did the text the criterion describes occur in `output.md`?". Produce it by
pasting each criterion + the agent's `output.md` into a judge session (see kit README), or wire your
harness's judge into `test.sh` step 2. Absent that file, `grade.py` grades Channel A only.
