# Dashboard

Single-file live dashboard for `run_benchmark.py` trials. Reads `output/trials_<slug>/` directories, exposes them at `/api/runs`, and serves a dark-themed SPA at `/` that auto-refreshes every 3 seconds.

Zero dependencies beyond the standard library (Tailwind is loaded via CDN in the browser).

## Quick start

Terminal 1 — run a benchmark job:

```bash
python run_benchmark.py -t config/general.yaml -m opus --source harbor --tasks-dir tasks --layout trials --output-dir output
```

Terminal 2 — launch the dashboard:

```bash
python3 dashboard.py
```

Open http://127.0.0.1:8080. The dashboard picks up new `trials_<slug>/` directories as they land and refreshes selection-preserved every 3 seconds.

## CLI flags

| Flag | Default | Purpose |
|---|---|---|
| `--dir` | `output` | Root directory containing `trials_<slug>/` |
| `--port` | `8080` | Bind port on 127.0.0.1 |

Point at any output tree that follows the trials layout:

```bash
python3 dashboard.py --dir output_all --port 9090
```

## Directory contract

The dashboard expects this layout under `--dir`:

```
output/
├── pass_summary.json          # top-level global rollup (dashboard ignores)
├── summary.json               # top-level global rollup (dashboard ignores)
├── report.md                  # (dashboard ignores)
└── trials_<slug>/             # ONE per task
    ├── summary.json           # per-task aggregate: {task, model, metrics:{n, pass@1, pass@k, pass^k, ci95, failure_breakdown}, attempts:[...]}
    ├── pairs.jsonl
    ├── failure_analysis.json  # (optional)
    ├── ground_truth/          # (optional)
    └── trajectories/
        └── <model>/
            └── run_N/
                ├── report.json         # {task, model, seed, attempt, passed, reward, completion_rate, misbehaving_rate, test_weights_percentage, rubric_weights_percentage, tokens:{prompt,llm,tool}, tool_summary:{tool_cnt, valid_tool_calls, invalid_tool_calls, error_tool_calls}}
                ├── reward.json         # (fallback) top-level reward
                ├── diagnosis.json      # (optional) {failure_class, reason}
                ├── verifier/
                │   └── reward.json     # {reward, graph_f1, graph_precision, graph_recall, matched_nodes, missing_nodes, rubric_score, grader}
                └── agent/
                    └── trajectory.json # {steps:[{tool, arguments, response}...], final_message}
```

The dashboard scans `output/` for entries starting with `trials_`, so top-level files (`pass_summary.json`, `report.md`, `summary.json`) are ignored — they belong to `run_benchmark.py`'s post-loop rollup, not to individual tasks.

## HTTP API

Three endpoints:

- `GET /` — dashboard HTML
- `GET /api/runs` — list of task summaries (JSON array)
- `GET /api/runs/<id>` — task detail (JSON object with `runs[]` per attempt)

`<id>` is the trials directory name including the `trials_` prefix, e.g. `trials_all-server-concierge`.

Sample `GET /api/runs` element:

```json
{
  "id": "trials_all-server-concierge",
  "task": "mcp-stump/all-server-concierge",
  "display": "all-server-concierge",
  "model": "opus",
  "started_at": "2026-08-11T16:02:46+00:00",
  "finished_at": "2026-08-11T16:15:22+00:00",
  "n_attempts": 1,
  "reward": 0.0,
  "passed": false,
  "grader": "graph_f1+efs(plan)",
  "quadrant": null,
  "completion_rate": 0.0,
  "misbehaving_rate": 0.0,
  "pass_at_1": 0.0,
  "pass_at_k": {"1": 0.0},
  "failure_class": "refused",
  "graph_f1": 0.0,
  "rubric_score": null,
  "tests_percentage": null,
  "valid_tool_calls": 0,
  "invalid_tool_calls": 0,
  "error_tool_calls": 0,
  "prompt_tokens": 192580,
  "llm_tokens": 1023,
  "tool_tokens": 0,
  "path": "output/trials_all-server-concierge"
}
```

## UI overview

- **Header** — logo, Live pulse, refresh countdown, task search filter, manual refresh button
- **4 metric cards** — Total Tasks · Passed (reward ≥ 0.8) · Avg Reward · Total Tokens
- **Left panel** — one card per task with quadrant/failure badge + reward progress bar + last-updated timestamp
- **Right panel** — 4 tabs:
  - **Overview** — summary card (task, model, attempts, avg reward, pass@1, failure class) + tool usage + tokens + per-attempt reward bars
  - **Trajectory** — collapsible steps per attempt with `tool → args → response` chunks, plus final message
  - **Reward** — per-attempt scoreboard with graph F1, rubric, completion, misbehave, test %, and diagnosis when present
  - **Raw** — pretty-printed JSON of the detail payload

Auto-refresh every 3s. Selection preserved across refreshes.

## Reward preference (multi-source fallback)

For each task, the dashboard reads reward from the first source that has one:

1. `trajectories/<model>/run_N/verifier/reward.json` → `reward`
2. `trajectories/<model>/run_N/reward.json` → `reward`
3. `trajectories/<model>/run_N/report.json` → `reward`
4. Fallback: mean of `summary.json → attempts[].reward`

## Backgrounding

`nohup`:

```bash
nohup python3 dashboard.py --port 8080 > /tmp/complexmcp_dashboard.log 2>&1 &
```

`systemd` user unit (`~/.config/systemd/user/complexmcp-dashboard.service`):

```ini
[Unit]
Description=ComplexMCP dashboard

[Service]
Type=simple
WorkingDirectory=%h/Documents/complex-mcp
ExecStart=/usr/bin/python3 dashboard.py
Restart=on-failure

[Install]
WantedBy=default.target
```

## Security

- Binds `127.0.0.1` only. No auth.
- Reads only from `--dir`.
- Tailwind CSS is loaded from the CDN; the dashboard needs internet on the browser side for styling.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Loading…` never leaves | `--dir` empty or no `trials_*` subdirs — start a benchmark run |
| Task shows `—` reward | Neither `verifier/reward.json` nor `reward.json` nor `report.json` had `reward`; check that the trial completed |
| Trajectory tab empty | `agent/trajectory.json` missing or not a `{steps: [...]}` dict |
| Wrong port already bound | `--port 8081` (or another free port) |
| Selection lost after refresh | Task was renamed/removed under `output/` |

## Field mapping

Where each dashboard field comes from:

| Dashboard field | Source file · key |
|---|---|
| `task` | `summary.json` → `task` (fallback `report.json.task`) |
| `model` | `summary.json` → `model` (fallback dir name) |
| `n_attempts` | `summary.json` → `metrics.n` |
| `pass_at_1` | `summary.json` → `metrics.pass@1` |
| `pass_at_k` | `summary.json` → `metrics.pass@k` |
| `failure_class` | `summary.json` → first attempt with `passed=false` `.failure_class` |
| `reward` | `verifier/reward.json` → `reward` (with fallbacks — see above) |
| `graph_f1` | `verifier/reward.json` → `graph_f1` |
| `rubric_score` | `verifier/reward.json` → `rubric_score` |
| `tests_percentage` | `report.json` → `test_weights_percentage` |
| `completion_rate` | `report.json` → `completion_rate` |
| `misbehaving_rate` | `report.json` → `misbehaving_rate` |
| `valid/invalid/error_tool_calls` | `report.json` → `tool_summary.*` |
| `prompt/llm/tool_tokens` | `report.json` → `tokens.*` |

## Files

- `dashboard.py` — single-file server + inline UI
- `DASHBOARD.md` — this document
