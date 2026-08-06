# Ground-truth generation

`gt_env.json` and `old_env.json` are seed-generated world snapshots (200 KB+),
so they must come from the ComplexMCP runtime once. They are **not committed**.

**Task:** Mark the messages from Sean Baker as read.
**Seed:** 42  **Apps:** LightTalk, LightShop

## Why a runtime-produced target?

This task's exact world-state mutation is task-specific. Rather than hand-
fabricate the target (which risks a wrong ground truth), we capture it by
replaying the reference trajectory (`solution/trajectory.json`) against the
seeded runtime and dumping the resulting state. The vendored judge
(`verify.py`) only scores leaves that differ between `old_env` and `gt_env`,
so a faithfully-captured target dump grades exactly the mutations this task
makes — no more, no less.

## Recipe

```bash
# 1) Boot the freshly-seeded app(s) and dump the INITIAL state -> old_env.json
docker compose -f ../environment/docker-compose.yaml up -d
until curl -sf http://localhost:8900/__health__; do sleep 1; done
curl -sf http://localhost:8900/__dump__ -o old_env.json

# 2) Replay the reference trajectory against the seeded runtime to reach the
#    TARGET state, then dump it -> target_env.json
#      - execute solution/trajectory.json's tool chain in order (or run the
#        oracle solution/solve.sh against a driver), then:
curl -sf http://localhost:8900/__dump__ -o target_env.json

# 3) Emit gt_env.json from the captured target (validates it differs from old)
python3 gen_gt.py target_env.json gt_env.json --old-env old_env.json
```

Now `old_env.json` + `gt_env.json` sit next to `test.sh`, and the verifier
(`verify.py`) grades `new_env` (dumped after the agent runs) against them:
Completion `Rc = recall/total`, Misbehave `Rb = misbehave/total`, success iff
`Rc == 1` and `Rb == 0`.

## Why not committed?

`old_env.json`/`gt_env.json` are 200 KB+ seed=42 world states that only
the runtime can produce correctly, so they are generated on demand, not stored.
