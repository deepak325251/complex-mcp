"""Persistent combination registry — plan §5, §7 decision #1, §9 invariant 1.

benchmark/data/combination_registry.json is the source of truth for
"one combination -> one task". It is git-tracked (survives across machines,
auditable in PRs) and APPEND-ONLY: an entry is never mutated, only added.

Write ordering (plan §9 invariant 2): the seed CLI appends here ONLY after the
bundle is emitted AND backed up, so a crash never burns a combination.

Atomicity: append writes to a temp file in the same directory and os.replace()s
it over the target, so a crash mid-write leaves the previous registry intact —
never a truncated JSON.
"""

from __future__ import annotations

import json
import os
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
DEFAULT_PATH = os.path.join(_ROOT, "benchmark", "data", "combination_registry.json")

_EMPTY = {"version": 1, "entries": []}


def load(path: str = DEFAULT_PATH) -> dict:
    """Load the registry, returning the empty shape if the file is absent."""
    if not os.path.exists(path):
        return dict(_EMPTY, entries=[])
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(_EMPTY, entries=[])
    data.setdefault("version", 1)
    data.setdefault("entries", [])
    return data


def _index(path: str) -> dict:
    """key -> entry, for O(1) membership."""
    return {e["key"]: e for e in load(path).get("entries", []) if e.get("key")}


def exists(key: str, path: str = DEFAULT_PATH) -> bool:
    """True if this canonical combination has already been authored."""
    return key in _index(path)


def get(key: str, path: str = DEFAULT_PATH) -> Optional[dict]:
    return _index(path).get(key)


def _atomic_write(data: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)                                # atomic on POSIX


def append(entry: dict, path: str = DEFAULT_PATH) -> dict:
    """Append one entry. Refuses to append a duplicate key (invariant 1).

    `entry` must carry at least {"key", "slug"}. Returns the written registry.
    """
    key = entry.get("key")
    if not key:
        raise ValueError("registry entry has no 'key'")
    data = load(path)
    if any(e.get("key") == key for e in data["entries"]):
        raise KeyError(f"combination already registered: {key} "
                       f"(refusing to author a duplicate)")
    data["entries"].append(entry)
    _atomic_write(data, path)
    return data
