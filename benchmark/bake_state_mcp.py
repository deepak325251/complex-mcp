"""Seed-driven, in-process world engine + state baker for multi-app tasks.

The Docker facade's `facade.dump` shipped empty (`output: {}`) for several apps
and ground truth was hand-fabricated against a world the facade never produces
(fictional page/PR ids). Both defects vanish when the world is booted
**in-process** at the task seed: every LightApp exposes a seeded session with
`get_session_dict()` returning real state — no Docker, no facade, no ports.

This module is the reusable world engine:

    boot_world(apps, seed)   -> {app: session}          (seeded, in-process)
    dump_world(sessions)     -> {app: {status, output}} (facade-compatible dump)
    run_oracle(sessions, spec)                            (execute declared writes)
    bake(task_dir, write=)   -> (old_env, gt_env)        (the full pipeline)

`bake` boots the task's apps at its seed, dumps `old_env`, replays a declared
oracle (`tests/oracle.json`) by *executing* real write calls, then dumps
`gt_env`. Ground truth is derived by execution, never hand-authored — so a task
can only bake if its target entities actually exist in the seeded world (the
check that stops "invented entity" GT from shipping). Pass `write=False` for a
dry run (used by benchmark.validate_task).

    tests/old_env.json   seeded world before the oracle
    tests/gt_env.json    seeded world after the oracle

new_env is produced at grade time by the running app in the same
`{app: {"status": "ok", "output": session_dict}}` schema; only old/gt are baked.

Seed resolution order: oracle.json "seed" -> task.toml [task.metadata] seed -> 42.

Usage:
    python -m benchmark.bake_state_mcp bundle/input/02-auth-v2-rollout-coordination
"""

from __future__ import annotations

import json
import os
import sys
import tomllib


# Explicit registry for the known mcp-stump apps (reliable). Apps NOT listed
# fall back to the naming convention in _boot, so the engine generalizes to any
# software/<App> that exposes a seeded session with get_session_dict().
_APP_SESSIONS = {
    "LightJira":       ("software.LightJira.jira",             "JiraSession"),
    "LightNotion":     ("software.LightNotion.notion",         "NotionSession"),
    "LightConfluence": ("software.LightConfluence.confluence", "ConfluenceSession"),
    "LightGithub":     ("software.LightGithub.github",         "GithubSession"),
    "LightSlack":      ("software.LightSlack.slack",           "SlackSession"),
    "LightShop":       ("software.LightShop.shop",             "ShopSession"),
    "LightWallet":     ("software.LightWallet.wallet",         "WalletSession"),
    "LightBudget":     ("software.LightBudget.budget",         "BudgetSession"),
    "LightTalk":       ("software.LightTalk.contact",          "ContactSession"),
}


def _candidates(app):
    """(module, class) pairs to try for an app's seeded session, most-specific
    first. Convention: software/<App>/<core>.py :: <Core>Session, where
    core = app without the 'Light' prefix (LightJira -> jira/JiraSession)."""
    if app in _APP_SESSIONS:
        yield _APP_SESSIONS[app]
    core = app[len("Light"):] if app.startswith("Light") else app
    yield (f"software.{app}.{core.lower()}", f"{core}Session")
    yield (f"software.{app}.session", f"Light{core}Session")
    yield (f"software.{app}.session", f"{core}Session")


def _boot(app, seed):
    """Boot one app's seeded session in-process. Tries the registry then the
    naming convention; if the convention's class name misses (e.g. casing like
    Quickbooks vs QuickBooks) or resolves to a wrapper without get_session_dict,
    scans the module for ANY *Session class that exposes get_session_dict."""
    import importlib
    import inspect
    last = None
    seen_mods = set()
    for modpath, clsname in _candidates(app):
        try:
            mod = importlib.import_module(modpath)
        except Exception as exc:                       # try the next candidate
            last = exc
            continue
        # exact convention class first, then any *Session class in this module
        cands = []
        exact = getattr(mod, clsname, None)
        if exact is not None:
            cands.append(exact)
        if modpath not in seen_mods:
            seen_mods.add(modpath)
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                if (name.endswith("Session") and obj is not exact
                        and getattr(obj, "__module__", None) == mod.__name__):
                    cands.append(obj)
        for cls in cands:
            try:
                sess = cls(os_cfg=None, seed=seed)
                if hasattr(sess, "get_session_dict"):
                    return sess
            except Exception as exc:
                last = exc
    raise SystemExit(f"could not boot a seeded session for {app!r}: {last}")


def boot_world(apps, seed):
    """{app: seeded session} — the in-process world at `seed`."""
    return {app: _boot(app, seed) for app in apps}


def _snapshot(session):
    """A deep, JSON-safe copy of the live session dict. get_session_dict() hands
    back the *live* internal dict, so without this snapshot `old` and `gt` alias
    the same object and every oracle write shows in both (false 'changed nothing')."""
    return json.loads(json.dumps(session.get_session_dict(), ensure_ascii=False))


def dump_world(sessions):
    """{app: {"status": "ok", "output": session_dict}} — the SAME schema the
    verifier's final_state.json (new_env) uses, so old/gt/new align under
    judge_env and the traj/state channels agree on paths."""
    return {app: {"status": "ok", "output": _snapshot(s)}
            for app, s in sessions.items()}


def _is_empty(x):
    return x is None or x == {} or x == [] or x == ""


def run_oracle(sessions, oracle):
    """Execute the declared write calls; abort loudly on any failure so a
    broken/unresolvable oracle can never silently bake a no-op GT."""
    n = 0
    for app, calls in (oracle or {}).items():
        if app not in sessions:
            raise SystemExit(f"oracle names app {app!r} not in booted apps")
        sess = sessions[app]
        for step in calls:
            meth = step.get("call")
            fn = getattr(sess, meth, None)
            if not callable(fn):
                raise SystemExit(f"{app}.{meth} is not a session method")
            r = fn(**step.get("args", {}))
            if isinstance(r, dict) and r.get("status") not in (None, "ok"):
                raise SystemExit(f"{app}.{meth} failed: {json.dumps(r)[:300]}")
            n += 1
    return n


def _split_tool(tool, apps):
    """Tool name -> (app, method). Handles 'App::tool', 'App.tool', and
    'App_tool'; falls back to the sole app owning a bare method."""
    if not tool:
        return None, None
    for sep in ("::", "."):                             # explicit App<sep>tool
        if sep in tool:
            a, t = tool.split(sep, 1)
            return a, t
    for app in apps:                                    # App_tool prefix
        if tool == app or tool.startswith(app + "_"):
            return app, (tool[len(app) + 1:] if len(tool) > len(app) else None)
    return (apps[0] if len(apps) == 1 else None), tool  # bare, single-app


def replay_trajectory(task_dir, trajectory, *, seed=None, apps=None, repo_root=None):
    """Reconstruct new_env by REPLAYING the agent's calls against a fresh seeded
    in-process world — the Layer-1 fix. When the Docker facade dumps empty
    (`output: {}`), this rebuilds the post-run world state from the trajectory
    alone (reads are harmless; only writes mutate), in the SAME schema old/gt use.

    Deterministic: same seed + same call sequence => same world, so a correctly
    seeded run reconstructs exactly. Individual calls that error (a read with odd
    args, a stale id) are skipped so one bad call can't sink the whole capture."""
    repo_root = repo_root or os.getcwd()
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    spec = {}
    op = os.path.join(task_dir, "tests", "oracle.json")
    if os.path.exists(op):
        spec = json.load(open(op, encoding="utf-8"))
    seed = seed if seed is not None else resolve_seed(task_dir, spec)
    apps = apps or spec.get("apps") or list(spec.get("oracle", {}).keys())

    sessions = boot_world(apps, seed)
    steps = trajectory.get("steps", []) if isinstance(trajectory, dict) else trajectory
    applied = 0
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        tool = s.get("tool") or s.get("function_name")
        app, meth = _split_tool(tool, apps)
        if not meth:
            continue
        if not app:
            # Bare, collision-free tool name (the toolbox presents unambiguous
            # tools without the server prefix, so the agent calls e.g.
            # `create_draft` not `LightGmail_create_draft`). _split_tool can't
            # resolve these in a multi-app task, so fall back to the sole app
            # that actually owns the method — otherwise the write (create_draft!)
            # is silently dropped and new_env never reflects the agent's mutation.
            owners = [a for a in sessions
                      if callable(getattr(sessions.get(a), meth, None))]
            if len(owners) != 1:
                continue                                # unknown / ambiguous bare name
            app = owners[0]
        if app not in sessions:
            continue
        fn = getattr(sessions[app], meth, None)
        if not callable(fn):
            continue
        args = s.get("arguments") or s.get("args") or {}
        if not isinstance(args, dict):
            continue
        resp = s.get("response")
        if isinstance(resp, dict):
            st = str(resp.get("status", "")).strip().lower()
            if st and st not in ("ok", "success", "200", "true", "created"):
                continue        # the call FAILED in the real run — replaying it here
                                # would credit an effect (a write, a misbehave) that
                                # never happened. Only successful calls mutate.
        try:
            fn(**args)
            applied += 1
        except Exception:
            continue                                    # skip un-replayable call
    return dump_world(sessions), applied


def repair_new_env(task_dir, new_env, old_env, gt_env, trajectory, *, seed=None):
    """Return a state-gradable new_env, reconstructed from the trajectory when
    the live dump under-captures the agent's writes.

    The live world dump re-reads a re-seeded session, so it silently drops the
    agent's mutations (a created draft, a sent message, a voided envelope). That
    shows up two ways: an *empty* dump (facade returned nothing) or a *stale*
    non-empty dump that is missing writes the agent actually made. Both are
    repaired here by replaying the trajectory in-process — the same
    boot_world+dump_world path that bakes old/gt, so schemas stay consistent and
    only the agent's *successful* calls mutate. The replay is preferred only when
    it is a strictly better capture of ground truth (higher Rc), so a healthy
    dump is never downgraded."""
    from benchmark.weighted_judge import state_admissibility, judge_env
    ok, reason = state_admissibility(old_env, new_env, gt_env)
    empty = (reason or "").startswith("empty_dump")
    try:
        rebuilt, applied = replay_trajectory(task_dir, trajectory, seed=seed)
    except Exception as exc:
        return new_env, {"repaired": False, "reason": f"replay_error:{type(exc).__name__}"}
    if not rebuilt:
        return new_env, {"repaired": False, "reason": reason}
    if empty:
        return rebuilt, {"repaired": True, "reason": reason, "calls_applied": applied}
    # Non-empty dump: swap in the replay only if it recalls more of GT than the
    # dump did (i.e. the dump missed writes). Faithful to misbehaviour too — a
    # successful bad call is applied by the replay and still counts.
    d = judge_env(old_env, new_env, gt_env)
    r = judge_env(old_env, rebuilt, gt_env)
    dump_rc = d["recall"] / d["total"] if d["total"] else 0.0
    rep_rc = r["recall"] / r["total"] if r["total"] else 0.0
    if rep_rc > dump_rc:
        return rebuilt, {"repaired": True, "reason": "stale_dump", "calls_applied": applied,
                         "dump_rc": round(dump_rc, 4), "replay_rc": round(rep_rc, 4)}
    return new_env, {"repaired": False, "reason": reason}


def resolve_seed(task_dir, spec=None):
    """Seed for a task: oracle.json 'seed' -> task.toml [task.metadata] seed -> 42."""
    if spec and spec.get("seed") is not None:
        return int(spec["seed"])
    toml_path = os.path.join(task_dir, "task.toml")
    if os.path.exists(toml_path):
        try:
            with open(toml_path, "rb") as fh:
                meta = tomllib.load(fh).get("task", {}).get("metadata", {})
            if meta.get("seed") is not None:
                return int(meta["seed"])
        except (OSError, tomllib.TOMLDecodeError, ValueError):
            pass
    return 42


def bake(task_dir, repo_root=None, write=True):
    """Boot -> dump old -> run oracle -> dump gt, with empty-dump and no-op
    guards. Returns (old_env, gt_env). `write=False` does a dry run (no files),
    which benchmark.validate_task uses to check a task without mutating it."""
    repo_root = repo_root or os.getcwd()
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    spec = json.load(open(os.path.join(task_dir, "tests", "oracle.json"),
                           encoding="utf-8"))
    seed = resolve_seed(task_dir, spec)
    apps = spec.get("apps") or list(spec.get("oracle", {}).keys())

    # Task-specific world overlay (software.utils.fixtures). Must be set BEFORE
    # boot so the baked world matches what the live app serves when the runner
    # exports the same COMPLEXMCP_FIXTURE for this task.
    if spec.get("fixture"):
        os.environ["COMPLEXMCP_FIXTURE"] = spec["fixture"]

    sessions = boot_world(apps, seed)
    old = dump_world(sessions)

    # Guard 1 (Layer-1 defense): the seeded dump must not be empty for any app —
    # the broken-capture signature we refuse to bake into ground truth.
    empty = [a for a, v in old.items()
             if _is_empty(v.get("output") if isinstance(v, dict) else v)]
    if empty:
        raise SystemExit(f"empty dump for {empty} — world did not boot; refusing "
                         f"to bake (this is the facade empty-dump bug).")

    n = run_oracle(sessions, spec.get("oracle"))
    gt = dump_world(sessions)

    # Guard 2 (Layer-2 defense): executing the oracle must actually change the
    # world, else the state channel would score total == 0 (a false "solved").
    if json.dumps(old, sort_keys=True, ensure_ascii=False) == \
       json.dumps(gt, sort_keys=True, ensure_ascii=False):
        raise SystemExit("gt_env == old_env: the oracle changed nothing — check "
                         "the target ids exist in this seed's world.")

    if write:
        out = os.path.join(task_dir, "tests")
        with open(os.path.join(out, "old_env.json"), "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False)
        with open(os.path.join(out, "gt_env.json"), "w", encoding="utf-8") as f:
            json.dump(gt, f, ensure_ascii=False)
        print(f"baked {out}/old_env.json and gt_env.json  "
              f"(seed={seed}, apps={apps}, oracle_calls={n})")
    return old, gt


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m benchmark.bake_state_mcp <task_dir> "
                         "[--check]")
    task_dir = sys.argv[1]
    write = "--check" not in sys.argv[2:]
    bake(task_dir, write=write)
    if not write:
        print(f"[check] {task_dir}: world boots, oracle mutates, GT derivable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
