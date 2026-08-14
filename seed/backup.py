"""Backup handoff — plan §5 (backup.py), Stage ②, §7 decision #2/#6.

Snapshots the emitted bundle to tasks_backup/<slug>/ with a SHA256 receipt, at
emit time (before the tasker touches anything), so the original mock data is
always recoverable. Fires AFTER emit and BEFORE the registry append (seed.py
ordering), per §9 invariant 2.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_tree(root: str) -> dict:
    """{relpath: sha256hex} for every file under root (skips __pycache__)."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            out[rel] = _sha256_file(full)
    return out


def snapshot(task_dir: str, backup_root: str = None, seed_args: dict = None,
             emitted_at: str = None) -> str:
    """Copy task_dir -> tasks_backup/<slug>/ and write receipt.json.

    Returns the backup dir. Raises if the backup already exists (a combination
    is authored once; a second snapshot signals a bug upstream).
    """
    task_dir = os.path.abspath(task_dir)
    slug = os.path.basename(task_dir.rstrip("/"))
    backup_root = backup_root or os.path.join(_ROOT, "tasks_backup")
    dest = os.path.join(backup_root, slug)
    if os.path.exists(dest):
        raise FileExistsError(f"backup already exists: {dest}")

    shutil.copytree(task_dir, dest,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    receipt = {
        "slug": slug,
        "emitted_at": emitted_at,          # ISO8601 stamped by caller (no Date.now here)
        "seed_args": seed_args or {},
        "sha256": _hash_tree(dest),
    }
    with open(os.path.join(dest, "receipt.json"), "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return dest


def verify(slug: str, backup_root: str = None) -> list:
    """Re-hash the backup and compare against receipt.json. Returns a list of
    mismatched paths ([] == intact). Used by the failure-catch gate (plan §13.3
    G3)."""
    backup_root = backup_root or os.path.join(_ROOT, "tasks_backup")
    dest = os.path.join(backup_root, slug)
    receipt_path = os.path.join(dest, "receipt.json")
    if not os.path.exists(receipt_path):
        return [f"receipt.json missing in {dest}"]
    with open(receipt_path, encoding="utf-8") as f:
        recorded = json.load(f).get("sha256", {})
    current = _hash_tree(dest)
    current.pop("receipt.json", None)
    mismatches = []
    for rel, h in recorded.items():
        if current.get(rel) != h:
            mismatches.append(rel)
    return mismatches
