"""Regression tests for the seed-plumbing fix.

Previously: every per-app session's __init__ did `self.rng =
random.Random(seed)` directly, and `resolve_seed` (imported in every one of
these files) was never actually called. On top of that, client/agent.py's
login RPC never sent a `seed` argument at all, so every login hit
`login(seed=None)` server-side -> `random.Random(None)` -> a genuinely
unseeded, unreproducible world, completely decoupled from a task's declared
seed or $COMPLEXMCP_SEED. That's what made a baked gt_env (baked in-process
at the correct seed via bake_state_mcp.boot_world) permanently mismatch the
live-served world: the two paths never agreed on a seed source.

These tests exercise the actual per-app session classes for the apps used by
the woodworks-commission-coordination task and assert:
  1. the same seed produces a byte-identical world twice (determinism), and
  2. different seeds produce different worlds (the seed is not dead).
Symptom (1) alone is necessary but not sufficient — the original bug also
produced "different-every-time" behavior when seed=None hit os.urandom, and
"always-identical-regardless-of-seed" behavior when the same live session was
reused across attempts. Asserting both (1) and (2) together pins down that
`resolve_seed`/the explicit `seed` kwarg is genuinely driving generation now.
"""
import random

from software.LightGmail.gmail import GmailSession
from software.LightQuickBooks.quickbooks import QuickbooksSession
from software.LightDocuSign.docusign import DocusignSession
from software.LightGoogleCalendar.google_calendar import GoogleCalendarSession
from software.LightInstagram.instagram import InstagramSession
from software.LightIssues.issues import IssuesSession

SESSION_CLASSES = [
    GmailSession, QuickbooksSession, DocusignSession,
    GoogleCalendarSession, InstagramSession, IssuesSession,
]


def _dump(cls, seed):
    return cls(os_cfg=None, seed=seed).get_session_dict()


def test_same_seed_is_deterministic():
    for cls in SESSION_CLASSES:
        a = _dump(cls, 1708)
        b = _dump(cls, 1708)
        assert a == b, f"{cls.__name__}: same seed produced different worlds"


def test_resolved_seed_actually_drives_the_rng():
    # Not every app's *content* is rolled from the seed -- LightGmail,
    # LightQuickBooks, LightDocuSign, LightGoogleCalendar and LightInstagram
    # all load their initial world from a static per-app corpus/*.yaml
    # (self.rng is only wired to TimeMachine + an otherwise-unused uuid()
    # helper for those apps), so asserting their get_session_dict() differs
    # by seed would be asserting something false about those apps' design,
    # not exercising the fix. What IS universally true, and what was
    # actually broken (resolve_seed was imported but dead in every app,
    # so `random.Random(seed)` always got whatever raw arg the caller
    # passed -- None from the live login path, since the client never sent
    # one either): the constructed self.rng must actually be seeded from
    # the resolved value, so its output stream differs across seeds and is
    # reproducible for a repeated seed. That's what every app's `self.rng`
    # feeds into at runtime (TimeMachine, minted ids for new entities).
    for cls in SESSION_CLASSES:
        r1708 = cls(os_cfg=None, seed=1708).rng.random()
        r42 = cls(os_cfg=None, seed=42).rng.random()
        r999 = cls(os_cfg=None, seed=999).rng.random()
        assert r1708 != r42 != r999 != r1708, (
            f"{cls.__name__}: self.rng produced the same output regardless "
            f"of seed -- resolve_seed() is not driving random.Random()"
        )
        # and it's reproducible for a repeated seed, not os.urandom noise
        assert cls(os_cfg=None, seed=1708).rng.random() == r1708


def test_seed_none_falls_back_to_resolve_seed_default():
    # seed=None must resolve through resolve_seed() (explicit arg -> env ->
    # 42), not fall through to random.Random(None) (os.urandom, unreproducible).
    # With $COMPLEXMCP_SEED unset, that means seed=None reproducibly == seed=42.
    import os
    saved = os.environ.pop("COMPLEXMCP_SEED", None)
    try:
        for cls in SESSION_CLASSES:
            assert _dump(cls, None) == _dump(cls, 42), (
                f"{cls.__name__}: seed=None did not resolve to the documented "
                f"default (42) -- resolve_seed() is not being called"
            )
    finally:
        if saved is not None:
            os.environ["COMPLEXMCP_SEED"] = saved
