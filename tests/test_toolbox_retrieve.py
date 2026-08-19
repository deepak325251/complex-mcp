"""Regression tests for Toolbox._retrieve_keys scoped-app retrieval.

whitfield-reunion-cookout: a task declaring 26 apps has a combined scoped
toolset well over 200 tools. The old `k_eff = max(k, min(scoped_total, 200))`
silently dropped any scoped tool past the 200th, ranked-lowest-first by RAG
similarity to the initial instruction -- exactly the "the agent claims a tool
doesn't exist" failure mode this suite exists to catch. k_eff must now cover
every scoped tool, uncapped.
"""
from client.agent import Toolbox


class _FakeRAG:
    """Returns the first k tools it was constructed with, in a fixed order --
    stands in for a real similarity ranking without needing an embedding index."""

    def __init__(self, ranked_key_names):
        self._ranked = ranked_key_names

    def read(self, query, k):
        return [{"meta_data": {"key_name": kn}} for kn in self._ranked[:k]]


def _make_toolbox(tools, ranked_key_names):
    tb = Toolbox(tools=tools, method="list_all")
    tb.rag = _FakeRAG(ranked_key_names)
    return tb


def _tool(app):
    return {"server": {"name": app}}


def test_scoped_retrieval_uncapped_beyond_200():
    # 250 tools all belonging to the task's one declared app, plus 5 tools
    # belonging to an app the task never logged into (must never appear).
    tools = {f"big_tool_{i}": _tool("BigApp") for i in range(250)}
    tools.update({f"other_tool_{i}": _tool("OtherApp") for i in range(5)})
    # RAG ranks only the first 40 BigApp tools highly; the rest rank below
    # the horizon and must be recovered by the top-up loop, not dropped.
    ranked = [f"big_tool_{i}" for i in range(40)] + [f"other_tool_{i}" for i in range(5)]
    tb = _make_toolbox(tools, ranked)

    keys = tb._retrieve_keys(query="do something", k=30, apps=["BigApp"])

    assert len(keys) == 250
    assert set(keys) == {f"big_tool_{i}" for i in range(250)}
    assert "other_tool_0" not in keys


def test_scoped_retrieval_still_excludes_unlogged_apps():
    tools = {"a1": _tool("AppA"), "a2": _tool("AppA"), "b1": _tool("AppB")}
    tb = _make_toolbox(tools, ["a1", "a2", "b1"])

    keys = tb._retrieve_keys(query="q", k=30, apps=["AppA"])

    assert set(keys) == {"a1", "a2"}


def test_unscoped_retrieval_still_respects_k():
    tools = {f"t{i}": _tool("AnyApp") for i in range(10)}
    tb = _make_toolbox(tools, [f"t{i}" for i in range(10)])

    keys = tb._retrieve_keys(query="q", k=3, apps=None)

    assert len(keys) == 3
