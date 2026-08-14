"""registry: append/exists, dedup rejection, atomic-write validity (plan §9)."""

import json

import pytest

from seed import registry


def test_load_empty_when_absent(tmp_path):
    data = registry.load(str(tmp_path / "nope.json"))
    assert data == {"version": 1, "entries": []}


def test_append_then_exists(tmp_path):
    p = str(tmp_path / "reg.json")
    assert not registry.exists("sha256:abc", p)
    registry.append({"key": "sha256:abc", "slug": "t"}, p)
    assert registry.exists("sha256:abc", p)


def test_duplicate_rejected(tmp_path):
    p = str(tmp_path / "reg.json")
    registry.append({"key": "sha256:abc", "slug": "t"}, p)
    with pytest.raises(KeyError):
        registry.append({"key": "sha256:abc", "slug": "t2"}, p)


def test_entry_needs_key(tmp_path):
    with pytest.raises(ValueError):
        registry.append({"slug": "t"}, str(tmp_path / "reg.json"))


def test_written_file_is_valid_json(tmp_path):
    p = str(tmp_path / "reg.json")
    registry.append({"key": "sha256:1", "slug": "a"}, p)
    registry.append({"key": "sha256:2", "slug": "b"}, p)
    with open(p, encoding="utf-8") as f:
        data = json.load(f)                       # must parse cleanly (atomic write)
    assert [e["key"] for e in data["entries"]] == ["sha256:1", "sha256:2"]


def test_no_tmp_left_behind(tmp_path):
    p = str(tmp_path / "reg.json")
    registry.append({"key": "sha256:1", "slug": "a"}, p)
    assert not (tmp_path / "reg.json.tmp").exists()
