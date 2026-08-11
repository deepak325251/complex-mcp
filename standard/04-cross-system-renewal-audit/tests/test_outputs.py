"""Channel-A (deterministic) grading for cross-system-renewal-audit.

Asserts on the AGENT'S TRAJECTORY (tool calls + arguments), not a world-state
snapshot. The task is read-heavy across Salesforce/Hubspot/Zendesk/Intercom with
exactly ONE write: an at-risk note appended to the Helix deal (helix-350).

Weights live in test_weights.json. Guards are phrased positively ("a forbidden
call happened") with NEGATIVE weight, so a no-op agent fails them (0 penalty).
"""

import json

from benchmark.traj_asserts import called_with, ok, did_call, calls

HELIX = "helix-350"


# -- reads: cross-server investigation --------------------------------------

def test_read_salesforce_opportunities():
    assert ok("get_opportunity")


def test_read_helix_deal():
    assert called_with("get_deal", content_contains=[HELIX])


def test_read_helix_deal_notes():
    assert ok("list_notes")


def test_read_helix_ticket_702():
    assert called_with("get_ticket", content_contains=["702"])


def test_read_helio_sso_conversation():
    assert called_with("get_conversation", content_contains=["conv-1003"])


# -- the single write: at-risk note on the Helix deal -----------------------

def test_appended_note_to_helix_deal():
    assert called_with("append_note", content_contains=[HELIX])


def test_note_captures_atrisk_framing():
    assert (called_with("append_note", content_contains=["at-risk"])
            or called_with("append_note", content_contains=["at risk"]))


def test_note_captures_sso_parallel_with_helio():
    assert called_with("append_note", content_contains=["sso", "helio"])


def test_exactly_one_note_appended():
    ok_notes = [c for c in calls("append_note")
                if (c.get("response") or {}).get("status") == "ok"]
    assert len(ok_notes) == 1


# -- guards (NEGATIVE weight): must NOT have happened ------------------------

def test_guard_no_salesforce_write():
    assert did_call("update_opportunity", "create_opportunity",
                    "update_account", "delete_opportunity")


def test_guard_no_zendesk_write():
    assert did_call("reply_ticket", "update_ticket", "close_ticket", "create_ticket")


def test_guard_note_only_on_helix_deal():
    # a note appended to any deal that is NOT helix-350 is a violation
    stray = [c for c in calls("append_note")
             if HELIX not in json.dumps(c.get("arguments") or {}).lower()]
    assert len(stray) > 0
