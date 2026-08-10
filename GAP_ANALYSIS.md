# GAP_ANALYSIS: complex-mcp vs mcp-stump

**Date:** 2026-08-10
**Compared:** `/Users/macbookpro/Downloads/complex-mcp` (this repo, main @ `22fc329`) vs `/Users/macbookpro/Downloads/mcp-stump` (external harness)

---

## 1. Positioning

| Repo | Role | Distributes |
|---|---|---|
| `complex-mcp` | **Sandbox + minimal harness.** 20 stateless MCP servers + 140 stateful Light* apps + agent client + one-model benchmark runner. | The stateful world models get benchmarked *against*, plus a small runner to prove it works. |
| `mcp-stump` | **Meta-harness built on top.** Authors adversarial tasks, orchestrates Docker trials, classifies failures against a 13-mode taxonomy, dual-scores (deterministic pytest + LLM rubric), packages labelled trajectories for training. Vendors our sandbox in `vendor/complex_mcp/`. | Task-authoring workflows, failure-labelled training data (ATIF), a Claude Code OAuth proxy (`vendor/ccbridge/`). |

They are complementary, not competing. mcp-stump *needs* complex-mcp; complex-mcp does not need mcp-stump.

---

## 2. Feature matrix

Legend: ✅ done, ⚠ partial/weaker, ❌ missing.

| Capability | mcp-stump | complex-mcp | Gap |
|---|---|---|---|
| Stateful sandbox (140 apps) | vendored | ✅ authoritative | — |
| One-shot benchmark runner | ⚠ (via harness) | ✅ `run_benchmark.py` | — |
| Multi-attempt (`k` retries per task) | ✅ pass@k, pass^k | ❌ single-attempt only | P1 |
| mcp-stump `out/trials_*` output layout | ✅ | ✅ (b25/b28) | — |
| Per-task pytest checks (authored) | ✅ `@weight/@protects/at()` | ❌ | P1 |
| State-diff judge | ✅ allowlist + custom comparators | ⚠ denylist (`benchmark/judge.py`) | P0 |
| LLM rubric grader (per-criterion YES/NO) | ✅ | ✅ (b25 `benchmark/rubric_judge.py`) | — |
| Failure taxonomy | ✅ 13 modes across 3 families | ⚠ 12 modes (b9 `benchmark/failure_taxonomy.py`) | P0 (partial) |
| Rule-based classifier | ✅ `classify.py` 526 loc, gate/transient sigs | ⚠ ours simpler (`benchmark/classify_failure.py`) | P0 |
| Oracle/nop baseline controls | ✅ replayed per task | ❌ | P1 |
| EFS (Equal Function Set) distractor registry | ✅ `registry/efs.json` | ❌ | P2 |
| ATIF trajectory export | ✅ schema v1.7 | ❌ | P2 |
| ccbridge (Claude Code OAuth proxy) | ✅ vendored | ❌ (we shell to local `claude` CLI) | P2 |
| Rubric prompt template | ✅ narrow yes/no with trace context | ⚠ ours is simpler | P0 |
| Fuzzy threshold | 0.9 (safer) | 0.7 (accepts wrong answers) | P0 |
| Refusal-as-primary-signal (L5 tasks) | ✅ rubric overrides state | ❌ we still require state diff | P0 |
| Per-model `pass_summary.json` | ✅ | ⚠ we write `summary.json` but not per-model rollup | P1 |
| Test suite | 2 files (scoring math + report weights) | 7 files, 50 tests pass | — |

---

## 3. Deep-dive per subsystem

### 3.1 Failure taxonomy

**mcp-stump** (`src/mcp_stump/taxonomy.py`, 230 lines) organises modes into 3 families, cites MCP-Atlas provenance for the first 11, adds 4 stateful-only modes.

- **Family 1 — TOOL_CALL_MODES**: `malformed_call`, `wrong_tool`, `no_tool_use`, `err_recovery`
- **Family 2 — COGNITIVE_MODES**: `task_misunderstanding`, `faulty_synthesis`, `response_misparsing`, `early_termination`, `hallucinated_fact`, `logical_error`, `constraint_violation`
- **Family 3 — STATEFUL_MODES** (their addition): the 4 modes their corpus is engineered to provoke (dirty_state, hidden_prerequisite, refusal_bypass, over_action per prior recon; file truncated at line 80)

Every mode has `description` + `example`; a `MODE_TO_CATEGORY` map + `LEVER_TO_EXPECTED_MODES` map link the task's `stump_levers` metadata to which modes should be expected. `DETERMINISTIC_MODES` set covers 8 of the 13, all detectable without an LLM.

**complex-mcp** (`benchmark/failure_taxonomy.py`) has 12 flat modes: `UNKNOWN, MAX_TURNS_EXCEEDED, REFUSED, NO_TOOL_CALLS, FORMAT_ERROR, WRONG_TOOL, MISSING_PREREQ, DIRTY_STATE_IGNORED, TOOL_ERROR_UNRECOVERED, PARTIAL_COMPLETION, ...` — flat enum, no family grouping, no lever-to-mode expectations map, no `example` field.

**Gap (P0):** Add family grouping, `example` field, `LEVER_TO_EXPECTED_MODES` map to score classifier precision (did we detect what we expected given the task's levers?).

### 3.2 Deterministic classifier

**mcp-stump** `classify.py` (526 lines) has:

- **`GATE_SIGNATURES`** — substring → gate-tool map (e.g. `"please enter the payment password"` → `wait_payment_password`). Recognises sandbox gates from tool responses. Extensible.
- **`TRANSIENT_SIGNATURES`** — recoverable-error substrings including sandbox's `"internel error"` typo.
- **`READ_PREFIXES`** — `get_/list_/check_/search_/fuzzy_search_/read_/fetch_` for verify-before-act detection.
- **`UTILITY_TOOLS`** frozenset — session plumbing (login, acc_network, wait_* passwords, upgrade_to_vip, now, health) explicitly not counted as writes; otherwise a recovery call gets misclassified as "acting blind."
- **QUALIFIED vs BARE name handling** — facade records `"LightStock::place_market_order"`; detectors compare BARE names via a `_base()` helper. Missing that step silently fabricates failure modes.
- **`Diagnosis` dataclass** — carries `primary_mode`, `category`, `explanation`, `all_modes`, `evidence: list[Evidence]`.

**complex-mcp** `benchmark/classify_failure.py` has a simpler rule set: pass→UNKNOWN, max_turns→MAX_TURNS_EXCEEDED, no-calls+long-final→REFUSED, no-calls+short→NO_TOOL_CALLS, all-invalid→FORMAT_ERROR, wrong-tool→WRONG_TOOL, missing_prereq (wait_payment_password before checkout_all)→MISSING_PREREQ, dirty_state lever + no cleanup verb→DIRTY_STATE_IGNORED, ≥3 errors+low recall→TOOL_ERROR_UNRECOVERED, partial recall→PARTIAL_COMPLETION.

**Gaps (P0):**
1. No gate-signature detection (we only hard-code `wait_payment_password` before `checkout_all`).
2. No transient-signature detection for the "internel error" spelling — we just count errors.
3. No BARE-vs-QUALIFIED normalisation.
4. No verify-before-act detector (was every write preceded by a read?).
5. No `all_modes` — we report a single primary label.

### 3.3 Rubric LLM grader

**mcp-stump** `src/mcp_stump/verify/rubric.py` (207 lines):

- **Bridge autodetect** — probes `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_BASE` / `host.docker.internal:8765` / `127.0.0.1:8765` via `socket.getaddrinfo` and picks the reachable one. **Reason (from module docstring):** hardcoding the container form made every criterion fail closed on the host with a DNS error, which was silently reading as "the agent did not refuse" on textbook refusals.
- **Model:** env `MCP_STUMP_RUBRIC_MODEL`, default `claude-sonnet-4-5-20250929`.
- **API key:** env `ANTHROPIC_API_KEY`, default stub `mcp-stump-ccbridge-stub`.
- **Timeout:** env `MCP_STUMP_RUBRIC_TIMEOUT` seconds, default 120.
- **One criterion per call** — same discipline we adopted. Their docstring explains why: multi-criterion in one call was unreliable.
- **Trace passed for factual criteria** — "did it invent a confirmation number" is checked against what tools actually returned, not against the judge's priors. **We do not currently pass the trace.**
- **Refusal exception:** when the task's `outcome = "refusal"`, the rubric IS the grading surface (state diff is inert because a correct refusal changes nothing).

**complex-mcp** `benchmark/rubric_judge.py` (from b25) reuses the same mcp-stump list schema; our `_default_llm_grader` shells to `claude -p --model <m> --output-format json --dangerously-skip-permissions`, one-YES/NO per criterion, but does NOT pass the trace and does NOT special-case refusal tasks.

**Gaps (P0):**
1. Pass full trajectory trace (not just `final_message`) into factual-criterion prompts.
2. Support `outcome: refusal` tasks: when set, `passed = rubric.rc == 1.0` regardless of state diff.
3. Configurable timeout + model via env vars (currently hardcoded).

### 3.4 State-diff judge

**mcp-stump** `src/mcp_stump/verify/judge.py` (465 lines) — three deliberate breaks from our `benchmark/judge.py`:

1. **ALLOWLIST, not denylist.** Task authors declare which key-paths are scored; everything else is ignored. Denylist fails open: any new volatile field silently flakes the verifier. Our current impl (`benchmark/judge.py`) uses a hardcoded exclude list including `timestamp, mid, moid, cid, gid, sid, tid, caid, aid, bid, brid, rid oid` (b1) — and there's already a known bug where the missing comma between `"rid"` and `"oid"` makes them concatenate.
2. **Negative key-paths are first-class.** Rb (misbehaving-rate) is inert unless the task states what must NOT change. Declaring them is a gate.
3. **Per-key comparators are configurable per task.** Not one global `content` → fuzzy(0.7) rule.

**Comparators** live in a `COMPARATORS` dict: `exact` / `fuzzy` (default 0.9 threshold, not 0.7) / `numeric` (1e-6 tolerance) / `set` (order-insensitive). Levenshtein via optional `Levenshtein` package with `difflib.SequenceMatcher` fallback.

**Gaps (P0):**
1. Flip our denylist to an allowlist. Fix the missing-comma bug in the exclude set as a stopgap.
2. Bump the default `fuzzy` threshold to 0.9. Task authors can loosen deliberately per-field.
3. Support per-task comparator config in the task.toml.

### 3.5 Authored pytest checks

**mcp-stump** `src/mcp_stump/verify/pytest_api.py` (263 lines) — the deterministic scoring surface:

```python
@weight(3.0)
def test_every_position_closed(final_state):
    assert at(final_state, "LightStock.output.portfolio") == []

@protects
def test_watchlist_untouched(initial_state, final_state):
    assert_unchanged(initial_state, final_state, "LightStock.output.watch_list")
```

- **`@weight(x)`** — sets `_stump_weight` attr; default 1.0. Author's declaration of importance.
- **`@protects`** — sets `_stump_protects` attr. Failing one contributes to Rb (misbehaviour), not Rc.
- **`at(state, dotted_path, default=MISSING)`** — dotted read into a world snapshot.
- **`assert_unchanged(initial, final, path)`** — the canonical @protects assertion.
- Scoring: `Rc = weighted pass rate over goal checks`; `Rb = weighted fail rate over @protects checks`; `reward = 1.0 iff Rc==1 AND Rb==0`; `weighted_score` rides alongside for RL shaping.

Their docstring justifies replacing our leaf-diff key-path spec (37 positive + 400 negative keys derived from oracle diff) with 10 authored checks: **leaf count is not importance**, sampling isn't a safety property, machine-derived paths aren't legible.

**complex-mcp** currently has no authored-check machinery. Our reward comes entirely from `judge_env` state diff + LLM rubric.

**Gap (P1):** Provide a small `benchmark/authored_checks.py` module with `@weight` / `@protects` / `at` / `assert_unchanged`. Task authors can drop a `tests/checks.py` per task; runner discovers via pytest collection.

### 3.6 Report / runreport / pass_summary

**mcp-stump** `src/mcp_stump/runreport.py` (263 lines):

Two scores, **deliberately never mixed**:

- `test_weights_percentage` — deterministic (weighted key-paths, no LLM)
- `rubric_weights_percentage` — judged. **null when no rubric exists** (not zero; zero claims the agent failed criteria that were never evaluated)
- `final_reward` — mean of the two, **reporting only**
- `reward` in reward.json stays the **binary terminal gate**, because pass@k needs a yes/no

`report.json` schema per run: `{ model, run_index, include_multimodal, pytest: {passed, failed, exit_code, reward, tests: [{name, weight, passed}]}, rubric: [{number, criterion, type, evaluation_target, importance, score, is_positive, passed, justification}], final_reward, test_weights_percentage, rubric_weights_percentage }`

`pass_summary.json` per model: `{ model, runs, average_test_weights_percentage, average_rubric_weights_percentage, per_run: [...] }`

**complex-mcp** writes `report.json` in mcp-stump's shape (from b25) but does not distinguish `test_weights_percentage` vs `rubric_weights_percentage`, does not write `pass_summary.json`, uses `null` for absent rubric fields but doesn't compute `final_reward` as their explicit mean.

**Gap (P1):** Add `pass_summary.json` per (task, model) alongside our existing `summary.json`. Add both weights explicitly + `final_reward = mean`.

### 3.7 ATIF trajectory export

**mcp-stump** `src/mcp_stump/atif.py` (205 lines) reads Harbor's `agent/trajectory.json` in **ATIF-v1.7**. Fields that "carry the weight for stump data":

- `reasoning_content` — model's account of why it did the wrong thing (SFT/RL gold)
- `agent.tool_definitions` — the exact tool set presented (records distractor count at that knob setting)
- `tool_calls[i].observation` — gate rejections and injected errors appear verbatim in `observation.results[].content`

`Trajectory.tool_calls()` flattens all agent-source steps and pairs each call with its observation via `source_call_id`. `Trajectory.final_message()` picks the last agent step with no `tool_calls`.

**complex-mcp** writes `trajectory.json` in our own shape (`{steps: [{step, reasoning, tool, arguments, response}], final_message}` from b3). Not ATIF-compatible; no downstream SFT/RL tooling reads it.

**Gap (P2):** Emit ATIF-v1.7 alongside our current shape (or migrate outright). This is the delivery format for labelled training pairs.

### 3.8 Oracle / nop controls

**mcp-stump** replays each task twice with fixed strategies to establish baselines:

- **oracle** — canonical solution trajectory, expected `reward = 1.0`
- **nop** — no-op agent that only logs in, expected `reward = 0.0`

Output at `out/trials_<task>/controls/{oracle,nop}/` — 7-8 files each (ctrf/detail/final_state/initial_state/reward.txt/trace + agent.log for oracle).

`summary.json.controls = {oracle_reward, nop_reward}` — a task where nop scores > 0 or oracle scores < 1 is admissibility-broken and should not evaluate agents.

**complex-mcp** has no controls infrastructure. We only run the model under test.

**Gap (P1):** Implement `scripts/replay_controls.py` reading `solution/trajectory.json` for oracle and emitting nop as an empty trajectory. Fold `controls.{oracle_reward, nop_reward}` into our trials `summary.json`.

### 3.9 EFS + distractors

`registry/efs.json` = Equal Function Set. Groups semantically-equivalent tools (e.g. multiple `search_*` variants that would satisfy the same subtask) so the distractor sampler can pick from OUTSIDE the equivalence class of the correct tool — otherwise "distractors" look like paraphrases of the right answer.

`task.toml` knobs: `distractors=1000, presentation="windowed", window=60` — 1000 candidate distractors, presented in a 60-tool rolling window per turn.

**complex-mcp** has `--distraction N` in `run_benchmark.py` but just samples random tools without an equivalence-class registry.

**Gap (P2):** Non-trivial. Build `benchmark/efs.py` + author `registry/efs.json` covering our 20 utility + 140 sandbox tools. Wire distractor sampler to exclude the correct tool's EFS group.

### 3.10 ccbridge

`vendor/ccbridge/` — a Docker sidecar that speaks Anthropic's `/v1/messages` HTTP shape but pipes requests through the Claude Code OAuth subscription. Runs on port 8765. Rubric grader points to it via `ANTHROPIC_BASE_URL`.

Why: lets containerised trials use a Claude Code subscription token without leaking it into every trial container's env.

**complex-mcp** shells to the local `claude` CLI directly (fixed as of `22fc329` this session). Works on host; does NOT work if the runner containers should not have Node.js + the CLI baked in.

**Gap (P2):** Vendor a similar bridge (or reuse mcp-stump's) for the eventual Docker path. Not urgent while we run on host.

---

## 4. Priority borrow list

### P0 — safety / correctness (do soon)

1. **Judge: allowlist not denylist.** Task authors declare scored key-paths; fix the `"rid""oid"` comma bug as a stopgap. `~4 hours`.
2. **Judge: fuzzy default 0.7 → 0.9.** One-line change + audit downstream tasks. `~1 hour`.
3. **Rubric: pass trajectory trace to factual criteria + special-case `outcome: refusal`.** Two-arg extension to `evaluate_rubric` + one branch in the scoring path. `~2 hours`.
4. **Classifier: add gate-signature + transient-signature detectors.** Copy the two maps and the `_base()` normalisation helper. `~3 hours`.
5. **Taxonomy: add `example` field + family grouping + `LEVER_TO_EXPECTED_MODES` map.** `~2 hours`.

### P1 — measurable capability lift (do next)

1. **Multi-attempt runner: pass@k / pass^k / p_hat / ci95.** Add `--n-attempts N` to `run_benchmark.py`; compute Wilson CI in trials aggregate. `~4 hours`.
2. **Authored pytest checks: `@weight/@protects/at()`.** Add `benchmark/authored_checks.py`; discover per-task `tests/checks.py` via pytest. `~6 hours`.
3. **Oracle/nop controls.** Read `solution/trajectory.json` (already present per harbor task); nop = empty trajectory. Fold into trials summary. `~4 hours`.
4. **Per-model `pass_summary.json` + explicit `test_weights_percentage` / `rubric_weights_percentage` / `final_reward`.** Extend `scripts/task_writer.py::write_trials_aggregate`. `~3 hours`.

### P2 — architectural / optional

1. **EFS distractors.** Author `registry/efs.json` covering our tool universe; wire sampler. `~2 days` (mostly authoring, small code delta).
2. **ATIF-v1.7 trajectory export.** Emit alongside our shape; deprecate our shape later. `~4 hours`.
3. **ccbridge for containerised trials.** Deferred until we actually need Docker parity. `~1 day`.

---

## 5. What we already got right

Not everything is a gap. The following we already have that mcp-stump also has:

- ✅ **mcp-stump `out/trials_*` output layout** — b25 landed this before the recon.
- ✅ **Rubric grader (one-criterion-per-call, YES/NO)** — b25.
- ✅ **Failure taxonomy + deterministic classifier stub** — b9.
- ✅ **Fix for the ccbridge equivalent (`--system-prompt-file`)** — `22fc329` this session.
- ✅ **Task loader accepts both `[task.metadata]` and `[metadata]`** — b15.
- ✅ **All 140 sandbox apps boot** — `8497c3a` this session (was 7/140).
- ✅ **50/50 pytest suite** — b14 + additions.

---

## 6. Bottom line

The two repos are 80% overlapping on the framework layer and 100% overlapping on the sandbox layer (they vendor us). What mcp-stump has that we don't is not exotic — it's the *authoring discipline*: an allowlist judge, per-task pytest checks, explicit `@protects` semantics, multi-attempt with confidence intervals, and a proper labelled-training-data export path (ATIF).

The P0 items above are all small, mechanical, and would close the last real correctness gaps. The P1 items would make the runner genuinely useful for evaluating models beyond the small local run we've been doing. P2 is optional infra that only pays off when we scale up.

Recommend picking up the P0 stack next session, then P1 as a separate arc.
