# Three-container ComplexMCP setup

Layout:

- `servers` — 20 stateless utility MCP servers (ports 8000-8024, minus 8021)
- `software` — 141 Light* sandbox apps (ports 9000-9144)
- `runner` — runs `run_benchmark.py --source harbor --tasks-dir benchmark/harbor_final_all` against the two service containers, writes results into the host-mounted `runs/` directory, exits when done

All three share the same `complexmcp:latest` image (built from the top-level `Dockerfile`, which now includes Node.js and the `@anthropic-ai/claude-code` CLI so the runner can call the local Claude bridge).

## Prerequisites

- Docker + Docker Compose
- `CLAUDE_CODE_OAUTH_TOKEN` env var (from your Claude Code subscription) — set in your shell or in a `.env` next to `docker-compose.yml`

## Build the image

```
docker compose -f docker/docker-compose.yml build
```

## Run the default task set

```
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-... \
  docker compose -f docker/docker-compose.yml up --abort-on-container-exit
```

The runner exits after finishing; `--abort-on-container-exit` then shuts the two service containers down.

## Overrides

```
MODEL=claude-opus-4-8 METHOD=rag LIMIT=4 \
  CLAUDE_CODE_OAUTH_TOKEN=... \
  docker compose -f docker/docker-compose.yml up --abort-on-container-exit
```

To swap the runner entrypoint (e.g. use `run_benchmark.py` on the parquet dataset instead of harbor tasks):

```
docker compose -f docker/docker-compose.yml run --rm runner \
  python run_benchmark.py -m claude-opus-4-8 --method rag \
    -t config/general.docker.yaml --limit 5
```

## Results

Each run writes to `runs/<timestamp>__<model>__harbor4/` on the host:

- `report.md`, `summary.json`
- `tasks/task_NNN__<slug>/` per task, with `meta.json`, `trajectory.json`, `output.md`, `tool_summary.json`, `tokens.json`, `score.json`
