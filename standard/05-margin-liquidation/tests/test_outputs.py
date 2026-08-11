"""Channel-A (trajectory) grading for margin-liquidation.

Cross-server liquidation (LightStock) + news lookup (LightNews) + a single
message to the ACCOUNT HOLDER (LightTalk) under injected network faults. Guards
are phrased positively ("a forbidden thing happened") with negative weight.
"""
import json
from benchmark.traj_asserts import called_with, ok, calls

ACCOUNT_HOLDER = "user_FiBXJH9uAk5v8tFppnBp6z"   # seed=114514 session holder

def _ok(c): return (c.get("response") or {}).get("status") == "ok"

# -- reads / setup ----------------------------------------------------------
def test_read_pending_orders():   assert ok("get_pending_orders")
def test_read_portfolio():        assert ok("get_portfolio")

# -- margin release ---------------------------------------------------------
def test_cancelled_pending_order(): assert ok("cancel_order")

# -- hidden prerequisite: password gate re-arms before every order ----------
def test_authorized_each_order():
    # the password gate re-arms before EVERY order: at least one ok
    # authorization per placed order (here 3 holdings + 1 short = 4).
    n_orders = len([c for c in calls("place_market_order") if _ok(c)])
    assert n_orders >= 1 and sum(1 for c in calls("wait_trade_password") if _ok(c)) >= n_orders

# -- liquidate every holding ------------------------------------------------
def test_liquidated_pypl(): assert called_with("place_market_order", content_contains=["PYPL", "sell"])
def test_liquidated_sbux(): assert called_with("place_market_order", content_contains=["SBUX", "sell"])
def test_liquidated_zm():   assert called_with("place_market_order", content_contains=["ZM", "sell"])

# -- open the short ---------------------------------------------------------
def test_opened_aapl_short(): assert called_with("place_market_order", content_contains=["AAPL", "sell", "50"])

# -- this year's toy story --------------------------------------------------
def test_found_toy_story(): assert called_with("search", content_contains=["toy"]) and ok("get_news_url")

# -- the single message to the ACCOUNT HOLDER -------------------------------
def test_messaged_link_to_account_holder():
    assert called_with("send_message", content_contains=[ACCOUNT_HOLDER, "light://news"])
def test_exactly_one_message():
    assert len([c for c in calls("send_message") if _ok(c)]) == 1

# -- guards (NEGATIVE weight) ------------------------------------------------
def test_guard_message_to_other_contact():
    stray = [c for c in calls("send_message")
             if ACCOUNT_HOLDER.lower() not in json.dumps(c.get("arguments") or {}).lower()]
    assert len(stray) > 0
def test_guard_placed_buy_order():
    stray = [c for c in calls("place_market_order")
             if '"side": "buy"' in json.dumps(c.get("arguments") or {}).lower()]
    assert len(stray) > 0
def test_guard_messaged_non_link():
    stray = [c for c in calls("send_message")
             if _ok(c) and "light://news" not in json.dumps(c.get("arguments") or {}).lower()]
    assert len(stray) > 0
