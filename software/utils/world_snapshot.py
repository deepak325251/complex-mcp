"""Seedless world snapshots.

Freeze a session's *generated* world so it can be loaded verbatim at login
instead of being rolled from a seed (ETOM-style: the world is read, not rolled).

Why pickle rather than hand-written JSON per app: a session's world is an
arbitrary object graph — typed dataclasses, nested lists/dicts, a `random.Random`
that is *shared* by reference with helpers like `TimeMachine`. Pickle preserves
that graph, including the shared-rng identity and the exact post-generation rng
state, so runtime id/timestamp/network minting reproduces the old seeded sequence
byte-for-byte. One utility works for all ~140 apps; no per-app serializer.

Recipe per app:
  1. BEFORE making the session seedless, run a bake against the still-seed-based
     code:  bake_session(core_session_at_seed_42, path)
     (bake while the core class is imported under its normal module name, so the
     pickle's class reference matches the one that exists at load time).
  2. Make the core session's __init__ seedless:
        restore_into(self, path); self.os = <live connector>
     (restore_into copies the frozen attributes onto `self`; pickle never calls
     __init__, so a changed/seedless class body is fine.)
"""
from __future__ import annotations

import os
import pickle

# Per-connection attributes that must NOT be frozen into the world — they are
# rebuilt from the live login (os_cfg) each session.
_LIVE_ATTRS = ("os",)


# ---------------------------------------------------------------------------
# Seed architecture (default). The harness is seed-based: __init__ ROLLS the
# world from a seed (random.Random(seed)) so different seeds give different
# worlds (anti-memorisation, seed-based re-tiering). seed=42 reproduces the
# original frozen fixture exactly.
#
# The seedless static snapshot (world.pkl) is now an explicit escape hatch only:
# set COMPLEXMCP_SEED_MODE=static (or seedless/off/0/false/no) to load it.
# ---------------------------------------------------------------------------
def seed_mode() -> bool:
    """True iff apps should generate their world from a seed. This is the DEFAULT;
    only an explicit opt-out loads the frozen static snapshot."""
    return os.environ.get("COMPLEXMCP_SEED_MODE", "seed").strip().lower() not in (
        "static", "seedless", "snapshot", "frozen", "0", "false", "off", "no",
    )


def resolve_seed(seed=None) -> int:
    """The seed to roll the world from: explicit arg wins, else $COMPLEXMCP_SEED,
    else 42 (the fixture's own seed)."""
    if seed is not None:
        return int(seed)
    env = os.environ.get("COMPLEXMCP_SEED")
    if env not in (None, ""):
        return int(env)
    return 42


def bake_session(core, path) -> None:
    """Pickle `core`'s world to `path`, minus its live connection attrs."""
    stash = {k: getattr(core, k) for k in _LIVE_ATTRS if hasattr(core, k)}
    for k in stash:
        setattr(core, k, None)
    try:
        with open(path, "wb") as fh:
            pickle.dump(core, fh, protocol=pickle.HIGHEST_PROTOCOL)
    finally:
        for k, v in stash.items():
            setattr(core, k, v)


def restore_into(target, path):
    """Load a frozen world (from `path`) onto the live instance `target`.

    Copies the frozen attributes onto `target.__dict__`. The caller is
    responsible for (re)attaching live connection attrs (e.g. `target.os`)
    afterwards. Returns `target`.
    """
    with open(path, "rb") as fh:
        loaded = pickle.load(fh)
    target.__dict__.update(loaded.__dict__)
    return target
