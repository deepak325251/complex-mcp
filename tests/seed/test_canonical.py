"""canonical_key: order-independence, determinism, normalization (plan §5)."""

from seed.canonical import canonical_key, normalize


def test_app_order_independence():
    a = canonical_key(["LightShop", "LightTalk"], 7, 2, ["x", "y"], None)
    b = canonical_key(["LightTalk", "LightShop"], 7, 2, ["y", "x"], None)
    assert a == b


def test_determinism():
    args = (["LightShop"], 42, "adhoc", ["dirty_state"], "camping-gear")
    assert canonical_key(*args) == canonical_key(*args)


def test_seed_changes_key():
    base = (["LightShop"], 7, 2, [], None)
    assert canonical_key(*base) != canonical_key(["LightShop"], 8, 2, [], None)


def test_fixture_changes_key():
    assert canonical_key(["LightShop"], 7, 2, [], None) != \
        canonical_key(["LightShop"], 7, 2, [], "camping-gear")


def test_tags_change_key():
    base = (["LightShop"], 7, 2, [], None)
    assert canonical_key(*base) != canonical_key(*base, ["support"])


def test_tags_order_independent():
    a = canonical_key(["LightShop"], 7, 2, [], None, ["support", "billing"])
    b = canonical_key(["LightShop"], 7, 2, [], None, ["billing", "support", "billing"])
    assert a == b


def test_no_tags_equals_empty_tags():
    assert canonical_key(["LightShop"], 7, 2, [], None) == \
        canonical_key(["LightShop"], 7, 2, [], None, [])


def test_level_type_normalized():
    # int vs str level string-normalize the same
    assert canonical_key(["A"], 1, 2, [], None) == canonical_key(["A"], 1, "2", [], None)


def test_normalize_dedups_and_sorts():
    n = normalize(["B", "A", "A"], 1, 1, ["z", "a", "a"], None)
    assert n["apps"] == ["A", "B"]
    assert n["levers"] == ["a", "z"]
    assert n["fixture"] is None
