"""World contract — the replacement for trusting a seed.

A seed is not determinism, it is a *hope*. `MCP_STUMP_SEED=777` reproduces the
same world on the same corpus and code, and says nothing about whether that
world contains what the task needs. Every task handed to this harness broke on
exactly that gap:

  * `pre-travel-housekeeping` booked San Francisco -> Denver. Seed 777 has no
    such flight on any day of the window.
  * `portfolio-liquidation-vip-trip` booked San Francisco -> Seattle. Same.
  * All three shopped for products (`power adapter`, `umbrella`,
    `Sony WH-1000XM5`) that do not exist in a catalogue whose only categories
    are fruit, vegetable and home_appliances.
  * `complexmcp-l4-s42` asserted a dirty cart under `DIRTY_CART=0.6`, which is
    a coin flip, and seed 42 came up clean.
  * `LightStock.market_open` is `rng.choice([True, True, False])` with no tool
    to open it -- one seed in three makes any trading task unsolvable, and
    nothing reports why.

Each surfaced as a mid-run oracle crash with a misleading message, hours after
the seed was chosen.

A contract states the facts a task depends on, and `preflight` checks them
against the live sandbox BEFORE any inference is spent:

    [world]
    flights      = [{ from = "San Francisco", to = "Helsinki", within_days = 7 }]
    items        = [{ query = "vacuum", min_results = 2, unique_cheapest = true }]
    market_open  = true
    cart_min     = 1
    portfolio_min = 1
    contacts     = ["Arya Barnes"]

The seed still selects a world. The contract is what makes the selection
*checkable* -- so a bad roll fails in seconds with "no San Francisco -> Denver
flight in the next 7 days" instead of thirty minutes later inside an oracle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any


@dataclass
class Requirement:
    name: str
    ok: bool
    detail: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class PreflightResult:
    requirements: list[Requirement] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.requirements)

    @property
    def failures(self) -> list[Requirement]:
        return [r for r in self.requirements if not r.ok]

    def as_dict(self) -> dict:
        return {"ok": self.ok,
                "checked": len(self.requirements),
                "requirements": [r.as_dict() for r in self.requirements]}


def _unwrap(result: Any) -> Any:
    data = getattr(result, "structured_content", None)
    if data is None:
        content = getattr(result, "content", None)
        if content and getattr(content[0], "text", None) is not None:
            try:
                return json.loads(content[0].text)
            except (json.JSONDecodeError, TypeError):
                return content[0].text
        return result
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


async def preflight(facade_url: str, contract: dict) -> PreflightResult:
    """Check every declared requirement against the live sandbox."""
    from fastmcp import Client

    res = PreflightResult()
    if not contract:
        return res

    async with Client(facade_url) as c:
        async def call(tool: str, **args) -> Any:
            """Retry through injected transient faults.

            LightTalk injects recoverable errors at MCP_STUMP_NOISE_RATE. A
            preflight that treats one as a missing contact reports a false
            failure on a perfectly good world -- and at noise 0.30 it would do
            so on roughly a third of runs, which makes the whole gate
            untrustworthy. Recovering is exactly what the task under test is
            expected to do, so the checker must do it too.
            """
            for _ in range(5):
                try:
                    got = _unwrap(await c.call_tool(tool, args))
                except Exception as exc:  # noqa: BLE001
                    return {"status": "error", "output": str(exc)}
                body = str(got).lower()
                if any(k in body for k in ("network", "internel", "try again")):
                    try:
                        await c.call_tool("acc_network", {})
                    except Exception:  # noqa: BLE001
                        pass
                    continue
                return got
            return got

        def payload(r: Any) -> Any:
            return r.get("output") if isinstance(r, dict) else r

        # -- the clock anchors every date-relative requirement ---------------
        today = None
        now = payload(await call("now"))
        if isinstance(now, str) and len(now) >= 10:
            try:
                today = date.fromisoformat(now[:10])
            except ValueError:
                today = None

        # -- flights ---------------------------------------------------------
        for spec in contract.get("flights", []) or []:
            frm, to = spec.get("from"), spec.get("to")
            window = int(spec.get("within_days", 7))
            found, days = 0, []
            if today is None:
                res.requirements.append(Requirement(
                    f"flight {frm} -> {to}", False, "could not read the clock"))
                continue
            for off in range(window):
                d = (today + timedelta(days=off)).isoformat()
                r = await call("search_flights", departure=frm, arrival=to, date=d)
                out = payload(r)
                if isinstance(out, list) and out:
                    found += len(out)
                    days.append(d)
            res.requirements.append(Requirement(
                f"flight {frm} -> {to} within {window}d",
                found >= int(spec.get("min_results", 1)),
                f"{found} flight(s) on {len(days)} day(s): {days[:4]}" if found
                else f"NO flight on any of the next {window} days -- pick a "
                     f"reachable destination or a different seed"))

        # -- catalogue -------------------------------------------------------
        for spec in contract.get("items", []) or []:
            q = spec.get("query", "")
            out = payload(await call("fuzzy_search_items", item_name=q))
            hits = out if isinstance(out, list) else []
            prices = sorted(float(h["price"]) for h in hits
                            if isinstance(h, dict) and h.get("price") is not None)
            ok = len(hits) >= int(spec.get("min_results", 1))
            detail = f"{len(hits)} hit(s)"
            if ok and spec.get("unique_cheapest"):
                # "the cheapest X" must have exactly one answer, or the task is
                # ambiguous and the grader is arbitrary.
                if len(prices) < 2 or prices[0] == prices[1]:
                    ok, detail = False, f"cheapest is TIED at {prices[:2]}"
                else:
                    detail = f"{len(hits)} hit(s), cheapest {prices[0]} (next {prices[1]})"
            if not hits:
                # Deliberately does not name the categories: they differ by
                # seed and by which apps are mounted, and an earlier hardcoded
                # claim ("only fruit, vegetables and home appliances") was read
                # as fact and led to replacing a product that did exist.
                detail = (f"no catalogue match for {q!r} on this seed -- run "
                          f"`mcp-stump catalog LightShop --tools` and probe the "
                          f"live shop before choosing a product")
            res.requirements.append(Requirement(f"item {q!r}", ok, detail))

        # -- trading ---------------------------------------------------------
        if contract.get("market_open"):
            r = payload(await call("get_account_summary"))
            probe = payload(await call("get_portfolio"))
            closed = "market" in str(r).lower() and "clos" in str(r).lower()
            res.requirements.append(Requirement(
                "market_open", not closed,
                "market is CLOSED on this seed and no tool opens it -- "
                "every order will fail" if closed else "open"))
            if contract.get("portfolio_min"):
                n = len(probe) if isinstance(probe, list) else 0
                res.requirements.append(Requirement(
                    "portfolio_min", n >= int(contract["portfolio_min"]),
                    f"{n} position(s) held"))

        # -- shop cart -------------------------------------------------------
        if contract.get("cart_min"):
            out = payload(await call("get_cart_summary"))
            n = len(out) if isinstance(out, list) else 0
            res.requirements.append(Requirement(
                "cart_min", n >= int(contract["cart_min"]),
                f"{n} pre-existing cart item(s)"
                + ("" if n else " -- set MCP_STUMP_DIRTY_CART=1.0 rather than "
                                "leaving it to a coin flip")))

        # -- contacts --------------------------------------------------------
        for who in contract.get("contacts", []) or []:
            out = payload(await call("get_uid_from_name", name=who))
            ok = isinstance(out, str) and out.startswith("user")
            res.requirements.append(Requirement(
                f"contact {who!r}", ok, str(out)[:120]))

    return res


def load_contract(task_dir: Path) -> dict:
    """From `[world]` in task.toml, or tests/world_contract.json."""
    import tomllib

    toml = Path(task_dir) / "task.toml"
    if toml.is_file():
        cfg = tomllib.loads(toml.read_text())
        if cfg.get("world"):
            return cfg["world"]
    f = Path(task_dir) / "tests" / "world_contract.json"
    return json.loads(f.read_text()) if f.is_file() else {}
