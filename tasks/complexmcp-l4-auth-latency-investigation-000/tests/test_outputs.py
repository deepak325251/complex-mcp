"""Channel-A (deterministic) grading for auth-latency-investigation.

Asserts on the AGENT'S TRAJECTORY -- the tool calls it made, their arguments,
and their real responses -- NOT on a world-state snapshot. This is robust to the
host-vs-Docker state-export / seeding differences: it grades what the agent did.

Weights live in test_weights.json (one entry per function). Guards are phrased
positively ("a forbidden call happened") and carry a NEGATIVE weight, so a
no-op agent fails them (contributes 0) rather than dodging a penalty.
"""

from benchmark.traj_asserts import (
    ok, called_with, did_call, response_contains,
)

# The task-fixed anchors (named in instruction.md, NOT seed-dependent):
FAULT = "session_store.write"
RELEASE = "2.0.3"


# -- investigation: did it resolve the fingerprint and read context first? ----

def test_resolved_deadline_fingerprint_from_tracker():
    # It opened the tracker issue whose response names the DeadlineExceeded /
    # session_store.write fault.
    assert response_contains("get_issue", FAULT)


def test_read_the_active_incident_before_writing():
    assert ok("get_incident")


def test_read_the_latency_monitor():
    assert ok("list_monitors") or ok("get_monitor") or ok("query_metrics")


# -- the paper trail: cross-server value carriage --------------------------- --

def test_paging_note_pins_fingerprint_and_release():
    assert called_with("create_note", content_contains=[FAULT, RELEASE])


def test_github_followup_quotes_fingerprint_and_release():
    assert called_with("create_comment", content_contains=[FAULT, RELEASE])


def test_posted_two_channel_updates():
    assert ok("chat_post_message", min_calls=2)


def test_channel_updates_reference_the_fault():
    assert called_with("chat_post_message", content_contains=[FAULT])


# -- guards (NEGATIVE weights): must NOT have happened ------------------------

def test_guard_no_new_incident_opened():
    # forbidden: opening a second page/incident
    assert did_call("create_incident", "trigger_incident")


def test_guard_nothing_resolved_or_closed():
    assert did_call("resolve_incident", "close_issue", "close_incident")
