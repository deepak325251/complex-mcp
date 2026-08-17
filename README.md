## ComplexMCP: Evaluation of LLM Agents in Dynamic, Interdependent, and Large-Scale Tool Sandbox 

**ComplexMCP** is a benchmark that pushes LLM agents beyond isolated API calls into realistic, interdependent tool workflows. It provides over 300 meticulously tested tools across 7 stateful sandboxes — from office suites to financial systems — and reveals that even top-tier models fail to exceed 60% success rate, far behind human performance at 90%.

<p align="center">
  <a href="https://arxiv.org/abs/2605.10787" target="_blank">
    <img src="https://img.shields.io/badge/arXiv-2605.10787v1-b31b1b?logo=arxiv&logoColor=white&style=for-the-badge" alt="arXiv badge">
  </a>
  <a href="https://github.com/ATH-MaaS/complex-mcp" target="_blank">
    <img src="https://img.shields.io/badge/GitHub-ATH_MaaS/complex_mcp-181717?logo=github&logoColor=white&style=for-the-badge" alt="GitHub badge">
  </a>
</p>



![ComplexMCP](assets/complex-mcp.png)

### 1) Build Environment Via Docker

```bash
docker build -t complexmcp:latest .
```

```bash
docker run -d --name complexmcp \
  -p 8000-8007:8000-8007 \
  -p 9000-9006:9000-9006 \
  complexmcp:latest
```

### 2) Create `.env`

Create a `.env` file in the project root, following `.env.example` format.

```bash
cp .env.example .env
```

Then fill values in `.env` as needed.

### 3) Run Benchmark

```bash
python run_benchmark.py --tool-config config/general.yaml \
  --model [model_name]
```

### 4) One-command task runner

`scripts/run_task.sh` starts the required servers/apps in tmux, waits for them, runs the benchmark, then tears everything down.

```bash
# Run one harbor task
TASK=complexmcp-l1-s7-purchase-90-kg-of-limes-at-the-most-competitive-000 bash scripts/run_task.sh

# Bake GT for that task first, then run with real judging
BAKE_GT=1 TASK=complexmcp-l1-s7-purchase-90-kg-of-limes-at-the-most-competitive-000 bash scripts/run_task.sh

# Parquet dataset (has GT baked in — full judging)
TASKS_DIR=benchmark/data/data.parquet LIMIT=5 bash scripts/run_task.sh

# Bake GT for ALL 43 harbor tasks in one go
BAKE_GT=1 LIMIT=0 bash scripts/run_task.sh
```

Overrides: `MODEL`, `METHOD`, `LIMIT`, `TASK`, `TASKS_DIR`, `OUTPUT_DIR`.
Output: `runs/<timestamp>__<model>__<method>/tasks/task_NNN__<slug>/{meta.json, output.md, trajectory.json, tool_summary.json, tokens.json, score.json}`.

### 4b) Run the trajectory for ONE task locally (recommended)

`scripts/run_task_local.sh` runs a single task **end to end** on your machine: it starts exactly one `ccbridge` (Claude OAuth proxy on `:8765`), boots the task's apps at the task's own seed, waits for every port to listen, generates the agent trajectory, grades it with the weighted judge, then tears everything down. This is the command to use when you just want the trajectory for a task.

```bash
# bash scripts/run_task_local.sh <tasks-dir> <task-slug> [model]
bash scripts/run_task_local.sh inputs_1408_2 03-household-week-coordination
```

Options (environment variables):

- `CCBRIDGE_CREDS=/path/to/creds.json` — explicit Claude OAuth credentials JSON. If unset, the bridge falls back to `~/.claude/.credentials.json` (or the macOS Keychain / Claude Code login).
- `DRY_RUN=1` — bring up the bridge + apps and verify all ports, but **skip** the benchmark (leaves the sandbox running until Ctrl-C; handy for poking the tools by hand).
- `LAYOUT=mcp-stump` (default) writes results under `output/trials_<task>/...`; `LAYOUT=legacy` writes under `runs/<timestamp>/...`.
- Third positional argument overrides the model (default `claude-opus-4-8`).

The task's `seed`, `fixture`, and `apps` are read from its `task.toml`, so the live world always matches the baked ground-truth env. The trajectory and grading artifacts land next to each other (`trajectory.json`, `output.md`, `tool_summary.json`, `tokens.json`, `score.json`).

### 5) 3-container Docker stack

```bash
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-... \
  docker compose -f docker/docker-compose.yml up --abort-on-container-exit
```

Servers, software, and runner each run in their own container. See `docker/README.md`.



If you find this work helpful, please cite our paper:

```latex
@misc{li2026complexmcpevaluationllmagents,
      title={ComplexMCP: Evaluation of LLM Agents in Dynamic, Interdependent, and Large-Scale Tool Sandbox}, 
      author={Yuanyang Li and Xue Yang and Longyue Wang and Weihua Luo and Hongyang Chen},
      year={2026},
      eprint={2605.10787},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2605.10787}, 
}
```
