"""Regression tests for authored-world coverage across two mechanisms.

Each app's authored world lives in ONE of two places:
  * software/<App>/corpus/*.yaml -- for apps whose corpus can faithfully hold
    the state (baked in by scripts/bake_world_into_corpus.py). The corpus was
    COMPLETELY replaced with the authored data; a committed golden snapshot in
    tests/data/corpus_baked_state/<App>.json is the reference.
  * software/<App>/world.json -- for apps whose code transforms/generates the
    state (or that have no corpus); hydrate() loads it at boot.

Either way, booting the app with COMPLEXMCP_WORLD_DATA unset must reproduce the
authored world deterministically. COMPLEXMCP_WORLD_DATA remains an optional
override for per-task / scenario worlds.
"""
import glob
import importlib
import json
import os

import pytest

pytestmark = pytest.mark.filterwarnings("ignore")

SOFTWARE_DIR = os.path.join(os.path.dirname(__file__), "..", "software")
BAKED_DIR = os.path.join(os.path.dirname(__file__), "data", "corpus_baked_state")
# Apps whose get_session_dict() is genuinely {} (no state to hydrate/grade).
NO_STATE_APPS = {"LightNews", "LightSystem"}
# Known, documented hydration gaps -- container-kind mismatches that can't be
# round-tripped without a recoverable dict key. Keep this list honest.
KNOWN_GAPS = {}


def _world_path(app_name):
    return os.path.join(SOFTWARE_DIR, app_name, "world.json")


def _world_json_apps():
    return sorted(
        os.path.basename(os.path.dirname(p))
        for p in glob.glob(os.path.join(SOFTWARE_DIR, "*", "world.json"))
        if os.path.basename(os.path.dirname(p)) not in NO_STATE_APPS
    )


def _baked_apps():
    return sorted(os.path.basename(p)[:-5]
                  for p in glob.glob(os.path.join(BAKED_DIR, "*.json")))


def _construct_session(app_name):
    # Canonical world is the default -- no COMPLEXMCP_WORLD_DATA override.
    os.environ.pop("COMPLEXMCP_WORLD_DATA", None)
    for path in sorted(glob.glob(f"software/{app_name}/*.py")):
        modname = path[:-3].replace("/", ".")
        module = importlib.import_module(modname)
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and hasattr(obj, "get_session_dict") \
               and getattr(obj, "__module__", None) == module.__name__:
                try:
                    return obj(os_cfg=None, seed=42)
                except Exception:
                    continue
    return None


def _dump(session):
    return json.loads(json.dumps(session.get_session_dict(), default=str, sort_keys=True))


@pytest.mark.parametrize("app_name", _world_json_apps())
def test_world_json_apps_hydrate(app_name, monkeypatch):
    """Apps that keep world.json: hydrate() reproduces it from software/<App>/world.json."""
    monkeypatch.delenv("COMPLEXMCP_WORLD_DATA", raising=False)
    session = _construct_session(app_name)
    assert session is not None, f"{app_name}: could not construct session"
    dumped = _dump(session)
    with open(_world_path(app_name)) as fh:
        expected = json.loads(json.dumps(json.load(fh), sort_keys=True))
    for key, exp_val in expected.items():
        if key in KNOWN_GAPS.get(app_name, set()):
            continue
        assert dumped.get(key) == exp_val, f"{app_name}.{key}: world data not reflected"


@pytest.mark.parametrize("app_name", _baked_apps())
def test_baked_apps_serve_corpus(app_name, monkeypatch):
    """Apps baked into corpus: the corpus alone (no world.json) reproduces the
    authored state, matching the committed golden snapshot, deterministically."""
    monkeypatch.delenv("COMPLEXMCP_WORLD_DATA", raising=False)
    assert not os.path.isfile(_world_path(app_name)), \
        f"{app_name}: baked app must NOT keep a world.json"
    with open(os.path.join(BAKED_DIR, f"{app_name}.json")) as fh:
        expected = json.load(fh)
    d1 = _dump(_construct_session(app_name))
    d2 = _dump(_construct_session(app_name))
    assert d1 == d2, f"{app_name}: corpus-served state is not deterministic"
    for key, exp_val in expected.items():
        assert d1.get(key) == exp_val, f"{app_name}.{key}: corpus does not serve authored state"


def test_world_data_is_canonical_default(monkeypatch):
    """With no COMPLEXMCP_WORLD_DATA override, the authored world is served by
    default (from world.json here) -- deterministically, and in place of the
    seed-rolled world."""
    monkeypatch.delenv("COMPLEXMCP_WORLD_DATA", raising=False)
    from software.LightAuction.auction import AuctionSession

    s1 = AuctionSession(os_cfg=None, seed=42)
    s2 = AuctionSession(os_cfg=None, seed=42)
    assert s1.get_session_dict() == s2.get_session_dict()  # deterministic
    sellers = {l.seller for l in s1.listings.values()}
    assert "Denise Whitfield-Carter" in sellers  # authored world
    assert "seller_a" not in sellers              # NOT the old seed-rolled world
