"""
Auto-generated Channel-A test suite for a ComplexMCP harbour task.

Channel A (this file) is DETERMINISTIC. It asserts on the world-state DUMP that
the running ComplexMCP apps expose at $DUMP_URL (the same dump the old state-diff
verifier consumed as new_env.json), compared against the seed-generated initial
state ($OLD_ENV / old_env.json).

  * ALLOWED   : read entities out of the world-state dump (live API state) and the
                seed baseline; assert a mutation landed / carries the right value /
                a collection grew / an undesired mutation happened (negative weight).
  * FORBIDDEN : opening or reading the agent's deliverable (output.md, trajectory.json)
                or any file the AGENT wrote. Deliverable *content* is graded by the
                rubric (Channel B). The dump is the mock-server read-back, never a file
                the agent authored.

Convention B (polarity): every `assert` is phrased POSITIVELY (something DID happen /
IS present). "The agent did a bad thing" is encoded as a positive assertion carrying a
NEGATIVE weight in test_weights.json — never `assert not ...`. A crashed agent that
mutates nothing then FAILS the negative test (contributes 0), correctly earning no
penalty-dodge credit.

Tests are FLAT `def test_*()` functions. No classes, no fixtures, no conftest.
Weight for every test lives in test_weights.json, one entry per function name.
"""

import json
import os
from urllib.request import Request, urlopen

DUMP_URL = os.environ.get("DUMP_URL", "http://localhost:8900/__dump__")


# --------------------------------------------------------------------------- #
# World-state access — the ONLY data sources pytest may read.
# --------------------------------------------------------------------------- #
_DUMP_CACHE = {}


def dump():
    """Final world state. Prefers the in-process $NEW_ENV file (the benchmark runner writes the
    agent's final world dict there); falls back to the live $DUMP_URL read-back (harbour/docker).
    Cache is keyed to the source so repeated in-process grading (many episodes) never reuses a
    stale world state."""
    new_path = os.environ.get("NEW_ENV")
    key = new_path or DUMP_URL
    if _DUMP_CACHE.get("key") != key:
        if new_path:
            with open(new_path, encoding="utf-8") as f:
                data = json.load(f)
        else:
            req = Request(DUMP_URL, headers={"Accept": "application/json"}, method="GET")
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        _DUMP_CACHE.clear()
        _DUMP_CACHE.update(key=key, d=data)
    return _DUMP_CACHE["d"]


def old_env():
    """Seed-generated initial world state (baseline for delta assertions)."""
    path = os.environ.get("OLD_ENV", os.path.join(os.path.dirname(__file__), "old_env.json"))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def app(state, name):
    """The per-app INNER state from a world dump, e.g. app(dump(), 'LightShop').
    Each app is dumped as {"status": "ok", "output": <state>} (the login/logout envelope);
    this unwraps the `output` layer so callers get the real state (shops/cart/trans_history/...)."""
    node = state.get(name, {}) if isinstance(state, dict) else {}
    if isinstance(node, dict) and "output" in node and "status" in node:
        node = node.get("output") or {}
    return node


def collection(state, app_name, *keys):
    """The entities of a collection inside an app as a LIST, e.g. collection(dump(), 'LightShop',
    'shops') or (..., 'trans_history'). Normalizes both list collections and dict-keyed-by-id
    collections (e.g. shops keyed by sid, items keyed by tid) to a list of entity dicts."""
    node = app(state, app_name)
    for k in keys:
        node = node.get(k, {}) if isinstance(node, dict) else {}
    if isinstance(node, list):
        return [v for v in node if isinstance(v, dict)]
    if isinstance(node, dict):
        return [v for v in node.values() if isinstance(v, dict)]
    return []


def _match(item, preds):
    if not isinstance(item, dict):
        return False
    for k, v in preds.items():
        got = item.get(k)
        if callable(v):
            if not v(got):
                return False
        elif isinstance(got, str) and isinstance(v, str):
            if v.lower().strip() not in got.lower().strip():
                return False  # substring/contains for free text
        elif got != v:
            return False
    return True


def find(items, **preds):
    """All entities in a collection matching field predicates. A string predicate
    is a case-insensitive substring match; a callable predicate is applied to the
    field value; anything else is exact equality."""
    return [it for it in items if _match(it, preds)]


def count(items, **preds):
    return len(find(items, **preds))


def added(state, old, app_name, *keys, keyfield="id"):
    """Entities present in the final dump's collection but not in the baseline,
    identified by `keyfield`. Use this to prove the AGENT created something."""
    new_items = collection(state, app_name, *keys)
    old_items = collection(old, app_name, *keys)
    old_ids = {it.get(keyfield) for it in old_items if isinstance(it, dict)}
    return [it for it in new_items if isinstance(it, dict) and it.get(keyfield) not in old_ids]


# =========================================================================== #
# EXAMPLE TESTS — DELETE these and write your task's own flat test_ functions below.
# (Do NOT edit anything ABOVE this line — the accessor header is correct-by-construction.)
# These illustrate the three buckets for the triage reference task. Every weight
# has a matching entry in test_weights.json.
# =========================================================================== #

# --- positive: a mutation landed with the right value (headline outcomes) ---
def test_github_issue_created_in_auth_api():
    """A new issue was opened in orbit-labs/auth-api titled from the email subject."""
    issues = added(dump(), old_env(), "LightGithub", "issues", keyfield="number")
    hits = find(issues, repo="auth-api", title="Latency spike alert")
    assert len(hits) > 0, "no new orbit-labs/auth-api issue titled from the email subject"


def test_jira_high_priority_eng_ticket_created():
    """A new ENG Jira ticket was created at High priority referencing the issue."""
    tickets = added(dump(), old_env(), "LightJira", "issues", keyfield="key")
    hits = find(tickets, project="ENG", priority="High")
    assert len(hits) > 0, "no new High-priority ENG Jira ticket"


def test_slack_heads_up_posted_to_eng():
    """A single heads-up message was posted to #eng (C01ENG)."""
    msgs = added(dump(), old_env(), "LightSlack", "messages", keyfield="ts")
    hits = find(msgs, channel="C01ENG")
    assert len(hits) > 0, "no heads-up message in #eng (C01ENG)"


def test_calendar_triage_event_on_primary():
    """A 30-minute triage-huddle event was blocked on the primary calendar."""
    events = added(dump(), old_env(), "LightGoogleCalendar", "events", keyfield="id")
    hits = find(events, calendar="primary", summary="Triage")
    assert len(hits) > 0, "no triage-huddle event on the primary calendar"


# --- negative: an UNDESIRED mutation happened → NEGATIVE weight (Convention B) ---
def test_gmail_write_occurred():
    """Negative test: passes when the forbidden behavior is detected; its negative
    weight contributes as a penalty. LightGmail is read-only in this task."""
    sent = added(dump(), old_env(), "LightGmail", "sent", keyfield="id")
    drafts = added(dump(), old_env(), "LightGmail", "drafts", keyfield="id")
    assert len(sent) + len(drafts) > 0, "Gmail write detected (should be read-only)"


def test_slack_message_mentions_someone():
    """Negative test: passes when the forbidden behavior is detected; its negative
    weight contributes as a penalty. The heads-up must not @-mention anyone."""
    msgs = added(dump(), old_env(), "LightSlack", "messages", keyfield="ts")
    mentioned = find(msgs, text=lambda t: isinstance(t, str) and any(
        m in t for m in ("@channel", "@here", "<@U")))
    assert len(mentioned) > 0, "an @-mention was present in the Slack post"


def test_github_issue_in_wrong_repo():
    """Negative test: passes when the forbidden behavior is detected; its negative
    weight contributes as a penalty. The issue belongs only in auth-api."""
    issues = added(dump(), old_env(), "LightGithub", "issues", keyfield="number")
    wrong = find(issues, repo=lambda r: r in ("billing-api", "web-app", "infra", "docs"))
    assert len(wrong) > 0, "a Github issue landed in the wrong repo"
