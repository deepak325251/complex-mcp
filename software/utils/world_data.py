"""Bring-your-own world data: hydrate a session's fields from user-authored
JSON instead of the seed-rolled/random world.

Guarded by the ``COMPLEXMCP_WORLD_DATA`` env var, so it's inert unless a run
explicitly opts in. When set to a directory, and that directory contains
``<AppName>.json``, the JSON is loaded and used to REPLACE the named
top-level fields on the session -- not merged, not overlaid onto the seeded
world: the fields the JSON declares become the session's entire state for
those fields, same as the seed roll they take the place of. (Contrast with
``fixtures.py``, which overlays a couple of entities onto an otherwise
seeded world -- world data replaces a whole app's world wholesale.)

The JSON must mirror the session's own field shape -- generally the same
shape its ``get_session_dict()``/``asdict()`` dump already produces: dicts of
id -> dataclass keep their id keys, lists of dataclasses stay lists. Each app
registers, once, which JSON keys to hydrate, what dataclass their elements
are, and (when the JSON key doesn't match the live attribute name, e.g.
``get_session_dict()``'s "contacts" vs. the session's actual
``contacts_dict``) which attribute to write. Nested dataclass fields inside
those (e.g. Shop.items: Dict[str, Item]) are resolved automatically from the
nested dataclass's own type hints, so nested shapes don't need separate
registration.

Some apps derive extra state from the hydrated fields (e.g. LightTalk keeps
``uid_dict``/``uids``/``my_uid`` in sync with ``contacts_dict``) -- those
register a post-hydrate hook that runs once, after all fields are set.

Wiring:
  * run_benchmark exports COMPLEXMCP_WORLD_DATA from --world-data / task meta.
  * benchmark.bake_state_mcp exports it the same way for baking old_env/gt_env.
  * each participating app calls ``hydrate(self, "LightShop")`` at the end of
    its seed-branch __init__, after fixtures.apply().
"""
from __future__ import annotations

import dataclasses
import json
import os
import typing


def active_dir() -> str:
    return os.environ.get("COMPLEXMCP_WORLD_DATA", "").strip()


def _coerce(tp, value):
    """Rebuild `value` (plain JSON dict/list/scalar) into the shape `tp`
    declares, recursing into nested dataclass/Dict/List fields."""
    if value is None or tp is None:
        return value
    origin = typing.get_origin(tp)
    if origin is dict and isinstance(value, dict):
        args = typing.get_args(tp)
        vtype = args[1] if len(args) == 2 else None
        return {k: _coerce(vtype, v) for k, v in value.items()}
    if origin is list and isinstance(value, list):
        args = typing.get_args(tp)
        etype = args[0] if args else None
        return [_coerce(etype, v) for v in value]
    if dataclasses.is_dataclass(tp) and isinstance(value, dict):
        hints = typing.get_type_hints(tp)
        kwargs = {}
        for f in dataclasses.fields(tp):
            if f.name in value:
                kwargs[f.name] = _coerce(hints.get(f.name, f.type), value[f.name])
        return tp(**kwargs)
    return value  # scalar (str/float/int/bool) or unresolvable type: as-is


# --------------------------------------------------------------------------
# Per-app shapes: {app_name: () -> {json_key: spec}}
#
# spec is one of:
#   ("dict", ElementCls[, attr_name])   -- json_key's dict values are ElementCls
#   ("list", ElementCls[, attr_name])   -- json_key's list elements are ElementCls
#   ("scalar", coerce_fn, attr_name)    -- json_key's scalar value needs a
#                                           type conversion and/or a rename
#                                           (e.g. get_session_dict()'s "today"
#                                           string -> session._today datetime)
#
# attr_name defaults to json_key when omitted -- most apps' get_session_dict()
# keys already match their live attribute names 1:1.
#
# Lazily imported so this module doesn't couple to every app's classes.
# --------------------------------------------------------------------------
def _shop_shape():
    from software.LightShop.shop import Shop, CartItem, Transaction
    return {
        "shops": ("dict", Shop),
        "cart": ("list", CartItem),
        "trans_history": ("list", Transaction),
    }


def _budget_shape():
    from software.LightBudget.budget import Category, Transaction, Budget
    from datetime import datetime
    return {
        "categories": ("dict", Category),
        "transactions": ("dict", Transaction),
        "budgets": ("dict", Budget),
        # get_session_dict() dumps self._today as a "YYYY-MM-DD" string.
        "today": ("scalar", lambda v: datetime.fromisoformat(v), "_today"),
    }


def _talk_shape():
    from software.LightTalk.contact import Contact, Group
    return {
        # get_session_dict() calls this "contacts"; the live attr is contacts_dict.
        "contacts": ("dict", Contact, "contacts_dict"),
        "groups": ("list", Group),
    }


_SHAPES = {
    "LightShop": _shop_shape,
    "LightBudget": _budget_shape,
    "LightTalk": _talk_shape,
}


def _talk_post_hydrate(session) -> None:
    """LightTalk derives uid_dict/uids from contacts_dict, and my_uid/my_name/
    my_gender identify which contact is "me" -- all stale once hydrate()
    replaces contacts_dict wholesale. Rebuild them from the hydrated data,
    repointing "me" at whichever hydrated contact is tagged "me" (falls back
    to leaving the seed-rolled my_uid alone if none is tagged, so a partial
    JSON that doesn't declare "contacts" doesn't break identity)."""
    contacts = getattr(session, "contacts_dict", {})
    if not contacts:
        return
    session.uid_dict = {c.name: uid for uid, c in contacts.items()}
    session.uids = list(contacts.keys())
    for uid, c in contacts.items():
        if getattr(c, "tag", None) == "me":
            session.my_uid = uid
            session.my_name = c.name
            session.my_gender = c.gender
            break


_POST_HYDRATE = {
    "LightTalk": _talk_post_hydrate,
}


def hydrate(session, app_name: str) -> bool:
    """Load ``<COMPLEXMCP_WORLD_DATA>/<app_name>.json`` onto ``session``,
    replacing each field the JSON declares. Returns True if a file was found
    and applied, False if world data isn't active for this run (or no file
    exists for this app -- e.g. LightSystem's is empty)."""
    d = active_dir()
    if not d:
        return False
    path = os.path.join(d, f"{app_name}.json")
    if not os.path.isfile(path):
        return False
    with open(path) as fh:
        data = json.load(fh)
    shape_fn = _SHAPES.get(app_name)
    shape = shape_fn() if shape_fn else {}
    for key, value in data.items():
        spec = shape.get(key)
        if spec is None:
            setattr(session, key, value)  # no declared shape: raw JSON as-is
            continue
        kind = spec[0]
        if kind == "scalar":
            _, coerce_fn, attr_name = spec
            setattr(session, attr_name, coerce_fn(value))
            continue
        cls = spec[1]
        attr_name = spec[2] if len(spec) > 2 else key
        if kind == "dict" and isinstance(value, dict):
            setattr(session, attr_name, {k: _coerce(cls, v) for k, v in value.items()})
        elif kind == "list" and isinstance(value, list):
            setattr(session, attr_name, [_coerce(cls, v) for v in value])
        else:
            setattr(session, attr_name, value)
    post_fn = _POST_HYDRATE.get(app_name)
    if post_fn:
        post_fn(session)
    return True
