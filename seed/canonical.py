"""Canonical combination key — plan §5 / §7 decision #3.

A task is one point in the space (apps × seed × level × stump_levers × fixture).
The canonical key is the identity of that point, used by the registry to enforce
"one combination -> one task" (plan §9 invariant 1).

Order-independence is the explicit requirement: two tasks that name the same
apps/levers in a different order are the SAME combination and must collide. We
get that by sorting apps and levers before hashing. seed/level/fixture are
scalars so their normalization is just type coercion.
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from typing import Iterable, Optional


def normalize(
    apps: Iterable[str],
    seed: int,
    level,
    levers: Optional[Iterable[str]] = None,
    fixture: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
) -> dict:
    """The normalized combination dict the key is computed over.

    Exposed separately so the registry can store a human-readable copy of the
    exact inputs next to the opaque hash. `tags` is order-independent (a set of
    labels), so it is sorted+deduped like apps/levers.
    """
    return {
        "apps": sorted({str(a) for a in apps}),
        "seed": int(seed),
        "level": str(level),
        "levers": sorted({str(x) for x in (levers or [])}),
        "fixture": str(fixture) if fixture else None,
        "tags": sorted({str(t) for t in (tags or [])}),
    }


def canonical_key(
    apps: Iterable[str],
    seed: int,
    level,
    levers: Optional[Iterable[str]] = None,
    fixture: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
) -> str:
    """sha256 over the normalized combination -> "sha256:<hex>"."""
    payload = json.dumps(normalize(apps, seed, level, levers, fixture, tags),
                         sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_combo(task_dir: str) -> dict:
    """Read the combination fields straight from a bundle's task.toml.

    task.toml is the single source of truth for the key: apps/seed/level/
    stump_levers/fixture/tags all live under [task.metadata]. `level` uses the
    integer `level` key (falling back to capability_level only if absent), which
    is what the hash is computed over.
    """
    with open(os.path.join(task_dir, "task.toml"), "rb") as f:
        meta = tomllib.load(f).get("task", {}).get("metadata", {})
    return {
        "apps": meta.get("apps", []),
        "seed": meta.get("seed"),
        "level": meta.get("level", meta.get("capability_level")),
        "levers": meta.get("stump_levers", []),
        "fixture": meta.get("fixture"),
        "tags": meta.get("tags", []),
    }


def key_from_task_toml(task_dir: str) -> str:
    """Canonical key derived from the bundle's own task.toml (authoritative)."""
    c = read_combo(task_dir)
    return canonical_key(c["apps"], c["seed"], c["level"], c["levers"],
                         c["fixture"], c["tags"])
