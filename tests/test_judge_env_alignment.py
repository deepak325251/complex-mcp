"""State diff must align list entities by IDENTITY and ignore paths GT never describes.

Both defects produced the same symptom: enormous fabricated `misbehave` counts on
runs that made almost no writes and tripped zero guards (58/109/185/69 damaged
leaves against 6-11 required ones).

  index alignment   gt=[702,705,706] vs live=[701..708] compared ticket 702
                    against ticket 701 -- two unrelated records -- so every
                    differing field read as damage.
  ungradeable path  the baked snapshot is a THINNER projection than the live app
                    (no `transactions`/`comments`, no `created_at`/`description`,
                    and `charges.customer` is a name in the bake but an id live).
                    With gt == old == None, any live value read as damage.
"""

from benchmark.weighted_judge import judge_env, _index_by_id, _entity_id


def env(app, container, records):
    return {app: {"status": "ok", "output": {container: records}}}


# --- identity alignment ----------------------------------------------------

def test_curated_gt_slice_against_full_population_is_not_damage():
    """The live world holds every ticket; GT names only the ones the task cares
    about. The extras are pre-existing world, not agent damage."""
    old = env("A", "tickets", [{"id": 702, "status": "open"},
                               {"id": 705, "status": "open"}])
    gt = env("A", "tickets", [{"id": 702, "status": "solved"},
                              {"id": 705, "status": "open"}])
    new = env("A", "tickets", [{"id": 701, "status": "open"},
                               {"id": 702, "status": "solved"},
                               {"id": 703, "status": "open"},
                               {"id": 705, "status": "open"},
                               {"id": 708, "status": "open"}])
    r = judge_env(old, new, gt)
    assert r["misbehave"] == 0        # index alignment scored 4+ here
    assert r["recall"] == r["total"] == 1


def test_reordering_alone_is_not_damage():
    recs = lambda order: [{"id": i, "v": f"val{i}"} for i in order]
    old = env("A", "items", recs([1, 2, 3]))
    gt = env("A", "items", recs([1, 2, 3]))
    new = env("A", "items", recs([3, 1, 2]))
    assert judge_env(old, new, gt)["misbehave"] == 0


def test_a_real_change_to_a_named_entity_is_still_caught():
    """The fix must not blind the judge to genuine damage."""
    old = env("A", "items", [{"id": 1, "v": "keep"}, {"id": 2, "v": "keep"}])
    gt = env("A", "items", [{"id": 1, "v": "keep"}, {"id": 2, "v": "keep"}])
    new = env("A", "items", [{"id": 1, "v": "CLOBBERED"}, {"id": 2, "v": "keep"}])
    assert judge_env(old, new, gt)["misbehave"] == 1


def test_a_required_change_still_counts_as_recall():
    old = env("A", "items", [{"id": 1, "v": "before"}])
    gt = env("A", "items", [{"id": 1, "v": "after"}])
    new = env("A", "items", [{"id": 1, "v": "after"}])
    r = judge_env(old, new, gt)
    assert (r["recall"], r["total"], r["misbehave"]) == (1, 1, 0)


def test_missing_a_gt_entity_is_a_miss_not_a_pass():
    old = env("A", "items", [{"id": 1, "v": "before"}])
    gt = env("A", "items", [{"id": 1, "v": "after"}])
    new = env("A", "items", [])
    r = judge_env(old, new, gt)
    assert r["total"] == 1 and r["recall"] == 0


def test_records_without_ids_fall_back_to_positional():
    """No identity to align on -- positional is the only option, and must work."""
    old = env("A", "vals", [{"v": 1}, {"v": 2}])
    gt = env("A", "vals", [{"v": 9}, {"v": 2}])
    new = env("A", "vals", [{"v": 9}, {"v": 2}])
    r = judge_env(old, new, gt)
    assert r["recall"] == 1 and r["misbehave"] == 0


def test_index_by_id_requires_every_element_identifiable():
    """A half-identifiable list must not be silently half-graded."""
    assert _index_by_id([{"id": 1}, {"no_id": 2}]) is None
    assert _index_by_id([]) is None
    assert _index_by_id("nope") is None
    assert set(_index_by_id([{"id": 1}, {"id": 2}])) == {"id=1", "id=2"}


def test_entity_id_prefers_specific_fields_and_gives_up_cleanly():
    assert _entity_id({"id": 7, "name": "x"}) == "id=7"
    assert _entity_id({"name": "x"}) == "name=x"
    assert _entity_id({"unrelated": "x"}) is None
    assert _entity_id({"id": "  "}) is None        # blank is not an identity


# --- ungradeable paths -----------------------------------------------------

def test_field_absent_from_gt_is_not_damage():
    """created_at/description exist live but not in the bake."""
    old = env("A", "items", [{"id": 1, "v": "same"}])
    gt = env("A", "items", [{"id": 1, "v": "same"}])
    new = env("A", "items", [{"id": 1, "v": "same", "created_at": "2025-01-10"}])
    assert judge_env(old, new, gt)["misbehave"] == 0


def test_collection_absent_from_gt_is_not_damage():
    """Whole collections (transactions, comments) are missing from the bake."""
    old = {"A": {"status": "ok", "output": {"items": [{"id": 1, "v": "x"}]}}}
    gt = {"A": {"status": "ok", "output": {"items": [{"id": 1, "v": "x"}]}}}
    new = {"A": {"status": "ok", "output": {"items": [{"id": 1, "v": "x"}],
                                            "comments": [{"id": 9, "b": "hi"}]}}}
    assert judge_env(old, new, gt)["misbehave"] == 0


def test_a_field_gt_DOES_describe_is_still_graded():
    """The skip must be narrow: only when GT is silent AND old is silent."""
    old = env("A", "items", [{"id": 1, "v": "before"}])
    gt = env("A", "items", [{"id": 1, "v": None}])     # gt says: should become None
    new = env("A", "items", [{"id": 1, "v": "still-here"}])
    r = judge_env(old, new, gt)
    assert r["total"] == 1 and r["recall"] == 0
