from pathlib import Path

from benchmark.efs import (
    EFSIndex, Tool, _opposed, candidates, group, scope, stem,
)

_REGISTRY = Path(__file__).resolve().parent.parent / "registry" / "efs.json"


def test_registry_load_and_equivalents():
    idx = EFSIndex.load(_REGISTRY)
    eq = idx.equivalents("LightShop::search_items")
    assert "LightShop::fuzzy_search_items" in eq
    assert "LightShop::search_items" in eq
    # A tool with no entry resolves to just itself.
    assert idx.equivalents("LightShop::not_a_tool") == {"LightShop::not_a_tool"}


def test_candidates_pairs_shared_stem():
    a = Tool(server="LightShop", name="search_items",
             description="Search for items by name.", args=("item_name",))
    b = Tool(server="LightShop", name="fuzzy_search_items",
             description="Fuzzy-search for items by name.", args=("item_name",))
    pairs = candidates([a, b])
    assert len(pairs) == 1
    got = {pairs[0][0].id, pairs[0][1].id}
    assert got == {"LightShop::search_items", "LightShop::fuzzy_search_items"}


def test_group_connected_components():
    verified = [
        ("LightShop::a", "LightShop::b"),
        ("LightShop::b", "LightShop::c"),  # transitive: a~b~c collapse to one set
        ("LightTalk::x", "LightTalk::y"),
    ]
    idx = group(verified)
    assert idx.equivalents("LightShop::a") == {
        "LightShop::a", "LightShop::b", "LightShop::c",
    }
    assert idx.equivalents("LightTalk::x") == {"LightTalk::x", "LightTalk::y"}
    # Two connected components.
    assert len(idx.sets) == 2


def test_stem_scope_opposed_sanity():
    # stem strips variant affixes so search/fuzzy_search collapse.
    assert stem("fuzzy_search_items") == stem("search_items")
    assert stem("get_shop_id_by_name") == "get_shop_id"
    # scope distinguishes group-targeted operations.
    assert scope("send_message_to_group") == "_to_group"
    assert scope("send_message") == ""
    # opposed polarity: add vs remove are not equivalents.
    assert _opposed("add_friend", "remove_friend") is True
    assert _opposed("search_items", "fuzzy_search_items") is False
