"""SEED stage CLI — plan §5 (seed.py), §8 sequence, §9 invariants 1-2.

    python -m seed --k 2 --level L2 --slug my-task
    python -m seed --apps LightShop,LightTalk --level L2 --seed 7 --slug demo-a
    python -m seed --k 3 --level L3 --fixture camping-gear --slug reorder-x

Strict ordering (the whole point — a crash never burns a combination):

    sample -> canonical_key -> registry.exists? -> emit+bake -> backup -> append

Any exception between emit and append rolls back the partial bundle + backup and
leaves the registry untouched (§9 invariant 2).
"""

from __future__ import annotations

import argparse
import datetime
import os
import random
import shutil
import sys

import yaml

from seed import backup, canonical, registry
from seed.bake import emit_and_bake

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_AREAS = os.path.join(_HERE, "areas.yaml")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat()


def load_areas(path: str = _AREAS) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _default_slug(apps, seed, level_meta) -> str:
    lvl = level_meta["level"]
    tag = "-".join(a.replace("Light", "").lower() for a in apps)
    return f"complexmcp-l{lvl}-s{seed}-{tag}-000"


def sample(args, areas, rng):
    """Draw a combination, resampling on registry collision. Returns
    (apps, seed, level_key, level_meta, levers, fixture) or exits on an
    unresolvable explicit collision."""
    levels = areas["levels"]
    level_key = args.level or "L2"
    if level_key not in levels:
        raise SystemExit(f"--level {level_key} not in areas.yaml levels {list(levels)}")
    level_meta = levels[level_key]
    levers = list(level_meta.get("stump_levers", []))

    pool = list(areas["apps"]["stateful"])
    explicit_apps = [a.strip() for a in args.apps.split(",")] if args.apps else None
    if explicit_apps:
        bad = [a for a in explicit_apps if a not in pool]
        if bad:
            raise SystemExit(f"--apps {bad} not in areas.yaml stateful pool")
    k = args.k or areas.get("default_k", 2)

    fixture = args.fixture
    if fixture and fixture not in areas.get("fixtures", []):
        raise SystemExit(f"--fixture {fixture} not registered in areas.yaml")

    tags = sorted({t.strip() for t in args.tags.split(",") if t.strip()}) \
        if args.tags else []

    lo, hi = areas.get("seed_range", [1, 100000])
    explicit_everything = bool(explicit_apps) and args.seed is not None

    for _ in range(200):
        apps = explicit_apps if explicit_apps else sorted(rng.sample(pool, k))
        seed = args.seed if args.seed is not None else rng.randint(lo, hi)
        key = canonical.canonical_key(apps, seed, level_meta["level"], levers,
                                      fixture, tags)
        if not registry.exists(key):
            return apps, seed, level_key, level_meta, levers, fixture, tags, key
        if explicit_everything:
            raise SystemExit(
                f"combination already registered (key={key}). This exact "
                f"(apps, seed, level, levers, fixture, tags) was authored "
                f"before — change one of them (e.g. a new seed or tag).")
    raise SystemExit("could not find a fresh combination after 200 tries")


def run(args) -> int:
    areas = load_areas()
    rng = random.Random(args.rng_seed) if args.rng_seed is not None else random.Random()
    apps, seed, level_key, level_meta, levers, fixture, tags, key = sample(args, areas, rng)

    slug = args.slug or _default_slug(apps, seed, level_meta)
    task_dir = os.path.join(_ROOT, "tasks", slug)
    backup_dir = os.path.join(_ROOT, "tasks_backup", slug)

    seed_args = {"apps": apps, "seed": seed, "level": level_key,
                 "levers": sorted(levers), "fixture": fixture, "tags": tags,
                 "slug": slug}

    emitted, backed = False, False
    try:
        emit_and_bake(slug, apps, seed, level_meta, levers, fixture,
                      out_root=os.path.join(_ROOT, "tasks"), repo_root=_ROOT,
                      tags=tags)
        emitted = True
        # task.toml is authoritative: re-derive the key from the file we just
        # wrote and register THAT, so the registry can never disagree with the
        # bundle's own tags/apps/seed/... If it diverges from the deduped
        # pre-check key, the emitter dropped/renamed a field — roll back.
        toml_key = canonical.key_from_task_toml(task_dir)
        if toml_key != key:
            raise RuntimeError(
                f"emitter drift: dedup key {key} != task.toml key {toml_key}")
        key = toml_key
        # Backup is opt-in: git already tracks bundles and the world re-bakes
        # deterministically from the seed, so the snapshot is redundant by default.
        if args.backup:
            backup.snapshot(task_dir, seed_args=seed_args, emitted_at=_now_iso())
            backed = True
        registry.append({"key": key, "slug": slug, "ts": _now_iso(),
                         "apps": apps, "seed": seed, "level": level_key,
                         "levers": sorted(levers), "fixture": fixture,
                         "tags": tags})
    except BaseException as exc:                     # rollback partial combination
        if emitted and os.path.isdir(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)
        if backed and os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)
        print(f"[seed] FAILED, rolled back {slug}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1

    print(f"[seed] OK  bundle: tasks/{slug}/")
    if args.backup:
        print(f"[seed]     backup: tasks_backup/{slug}/  (receipt.json)")
    print(f"[seed]     registry: +1 entry ({key})")
    print(f"[seed]     apps={apps} seed={seed} level={level_key} "
          f"fixture={fixture or '-'} tags={tags or '-'}")
    print(f"[seed] next: author tasks/{slug}/ then  python -m seed.finish {slug}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("seed", description="Emit a unique task bundle skeleton.")
    p.add_argument("--k", type=int, help="number of apps to sample (ignored if --apps)")
    p.add_argument("--apps", help="comma-separated explicit app list")
    p.add_argument("--level", help="difficulty tier key from areas.yaml (default L2)")
    p.add_argument("--seed", type=int, help="explicit world seed (else sampled)")
    p.add_argument("--fixture", help="registered fixture name (optional)")
    p.add_argument("--tags", help="comma-separated tags (part of the combination hash)")
    p.add_argument("--slug", help="bundle slug (else complexmcp-lN-sS-<apps>-000)")
    p.add_argument("--rng-seed", type=int,
                   help="seed the sampler itself (reproducible sampling; tests)")
    p.add_argument("--backup", action="store_true",
                   help="also snapshot the emitted bundle to tasks_backup/ "
                        "(off by default — git + deterministic re-bake cover recovery)")
    return p


def main(argv=None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
