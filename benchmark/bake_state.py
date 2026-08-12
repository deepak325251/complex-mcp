"""In-process state baker for LightShop tasks (world + seed mechanism).

Boots the seeded LightShop world (static world.pkl, seed 42) *in-process* — no
Docker, no ports — replays a task's oracle, and writes the two snapshots the
state channel needs:

    tests/old_env.json   initial world (a pure function of the fixture)
    tests/gt_env.json    target world after the oracle acts

new_env is produced at grade time by the running app; only old/gt are baked.

The oracle is declared in tests/oracle_actions.json so ground truth is derived by
*executing* it (never hand-fabricated). Shape:

    {
      "clear_cart": true,
      "buy":  [ {"item": "Apple AirPods Pro (2nd Gen)", "shop": "Memory Market", "quantity": 1} ],
      "star": [ {"item": "Apple AirPods Pro (2nd Gen)", "shop": "Memory Market"} ]
    }

Item/shop names are resolved to live ids against the booted world, so a task can
only bake if its items actually exist in the fixture — which is the check that
stops "invented product" tasks from ever shipping.

Usage:
    python -m benchmark.bake_state standard/06-restock-pantry-guardrail
"""

from __future__ import annotations

import json
import os
import sys


def _load_shop_module(repo_root):
    sys.path.insert(0, repo_root)                                  # software.utils.*
    sys.path.insert(0, os.path.join(repo_root, "software/LightShop"))  # bare shop/session
    import shop as shopmod
    return shopmod


def _resolve(session, item_name, shop_name):
    """(shop_name, item_name) -> (sid, tid) against the live world."""
    sid = session.get_shop_id_by_name(shop_name)["output"]
    if not isinstance(sid, str) or not sid.startswith("shop_"):
        raise SystemExit(f"shop not found in world: {shop_name!r}")
    hits = [i for i in session.search_items(item_name)["output"]
            if i["shop"] == shop_name and i["name"] == item_name]
    if not hits:
        raise SystemExit(f"item not found in shop {shop_name!r}: {item_name!r} "
                         f"-- it is not stocked in this fixture, pick a real one")
    return sid, hits[0]["tid"]


def bake(task_dir, seed=42, repo_root=None):
    repo_root = repo_root or os.getcwd()
    shopmod = _load_shop_module(repo_root)
    os.chdir(repo_root)

    spec_path = os.path.join(task_dir, "tests", "oracle_actions.json")
    spec = json.load(open(spec_path, encoding="utf-8"))

    s = shopmod.ShopSession(os_cfg=None, seed=seed)
    old = s.get_session_dict()

    if spec.get("clear_cart"):
        for line in list(s.cart):
            s.delete_item_in_cart(line.caid)

    for buy in spec.get("buy", []):
        sid, tid = _resolve(s, buy["item"], buy["shop"])
        r = s.add_to_cart(sid, tid, int(buy.get("quantity", 1)))
        if r.get("status") != "ok":
            raise SystemExit(f"add_to_cart failed for {buy['item']!r}: {r}")

    if spec.get("buy"):
        for _ in range(50):                       # password gate is 10% flaky
            if s.wait_payment_password().get("status") == "ok":
                break
        r = s.checkout_all()
        if r.get("status") != "ok":
            raise SystemExit(f"checkout_all failed: {r}")

    for star in spec.get("star", []):
        sid, tid = _resolve(s, star["item"], star["shop"])
        r = s.star_item(sid, tid)
        if r.get("status") != "ok":
            raise SystemExit(f"star_item failed for {star['item']!r}: {r}")

    gt = s.get_session_dict()

    if json.dumps(old, sort_keys=True) == json.dumps(gt, sort_keys=True):
        raise SystemExit("gt_env == old_env: the oracle changed nothing -- "
                         "the state channel would score total=0")

    out_dir = os.path.join(task_dir, "tests")
    json.dump(old, open(os.path.join(out_dir, "old_env.json"), "w"), ensure_ascii=False)
    json.dump(gt, open(os.path.join(out_dir, "gt_env.json"), "w"), ensure_ascii=False)
    print(f"baked {out_dir}/old_env.json and gt_env.json  (seed={seed})")
    return old, gt


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m benchmark.bake_state <task_dir> [seed]")
    task_dir = sys.argv[1]
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    bake(task_dir, seed=seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
