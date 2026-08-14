"""Backfill the registry from existing bundles — plan §6 Phase 1.

Replays every already-shipped bundle's (apps, seed, level, levers, fixture)
into benchmark/data/combination_registry.json so the seed CLI can never re-issue
a combination a legacy task already occupies. Multiple legacy tasks can share
one combination key (e.g. many L1/seed=42 tasks) — the first is recorded and
the rest are counted as pre-existing occupants, not errors.

    python -m seed.backfill                 # scan the default bundle roots
    python -m seed.backfill <dir> [<dir>..] # scan explicit roots
"""

from __future__ import annotations

import os
import sys

from seed import canonical, registry

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

_DEFAULT_ROOTS = [
    os.path.join(_ROOT, "benchmark", "harbor_final_all"),
    os.path.join(_ROOT, "bundle", "input"),
]


def _bundles(root):
    if not os.path.isdir(root):
        return
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if os.path.isfile(os.path.join(d, "task.toml")):
            yield d


def run(roots=None) -> dict:
    roots = roots or _DEFAULT_ROOTS
    added = skipped = incomplete = 0
    for root in roots:
        for d in _bundles(root):
            # task.toml is the source of truth for every hashed field, incl tags.
            c = canonical.read_combo(d)
            if not c["apps"] or c["seed"] is None:
                incomplete += 1
                continue
            key = canonical.key_from_task_toml(d)
            try:
                registry.append({"key": key, "slug": os.path.basename(d),
                                "apps": sorted(c["apps"]), "seed": int(c["seed"]),
                                "level": str(c["level"]),
                                "levers": sorted(c["levers"]),
                                "fixture": c["fixture"], "tags": sorted(c["tags"]),
                                "source": "backfill"})
                added += 1
            except KeyError:
                skipped += 1                        # combination already recorded
    return {"added": added, "skipped_duplicate": skipped, "incomplete": incomplete}


def main(argv=None) -> int:
    roots = argv if argv is not None else sys.argv[1:]
    stats = run(roots or None)
    print(f"[backfill] added={stats['added']} "
          f"duplicate_combinations={stats['skipped_duplicate']} "
          f"incomplete_meta={stats['incomplete']}")
    print(f"[backfill] registry now has {len(registry.load()['entries'])} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
