#!/usr/bin/env python3
"""Populate the LightStock frozen world (world.pkl) with holdings + an unfilled order.

The harness is seedless: LightStock serves ONE frozen software/LightStock/world.pkl.
The default fixture has an EMPTY portfolio, so any "liquidate your holdings" task
(e.g. 05-margin-liquidation) is unsolvable -- there's nothing to sell.

This bakes real holdings (PYPL/SBUX/ZM) and one unfilled margin-tying order into
the frozen world, using the app's OWN Position/Order classes so the shape is
correct. Run it ONCE, then re-run the task.

    .venv/bin/python scripts/populate_stock_world.py

Idempotent: it sets the portfolio explicitly, so re-running just re-bakes the
same state.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "software" / "LightStock"
WORLD = APP / "world.pkl"

# The pickle references a bare `stock` module, so the app dir must be importable.
sys.path.insert(0, str(APP))
sys.path.insert(0, str(REPO))


def _load_stock_module():
    spec = importlib.util.spec_from_file_location("stock", str(APP / "stock.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stock"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    stock = _load_stock_module()
    from software.utils.world_snapshot import bake_session

    s = stock.StockSession(os_cfg=None)  # restores from world.pkl

    # Holdings to liquidate (all in the catalog; entry prices above/below current
    # so the account shows real P&L). quantity, avg_price.
    s.portfolio = {
        "PYPL": stock.Position("PYPL", 100, 105.00),
        "SBUX": stock.Position("SBUX", 50, 120.00),
        "ZM": stock.Position("ZM", 80, 90.00),
    }

    # An unfilled limit order that ties up margin -> the task's
    # "release whatever margin is tied up in orders that haven't filled".
    s.pending_orders = []
    s.password_verified = True
    r = s.place_limit_order("MSFT", "buy", 10, 300.00)
    s.password_verified = False
    print(f"pending order: {r.get('status')}  frozen_margin={s.frozen_margin}")

    bake_session(s, WORLD)
    print(f"re-froze {WORLD}")

    # verify
    s2 = stock.StockSession(os_cfg=None)
    print("portfolio :", [(p.ticker, p.quantity, p.avg_price) for p in s2.portfolio.values()])
    print("pending   :", len(s2.pending_orders), "order(s), frozen_margin=", s2.frozen_margin)
    ok = (len(s2.portfolio) == 3 and len(s2.pending_orders) == 1)
    print("OK" if ok else "!! population did not stick")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
