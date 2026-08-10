"""The facade MCP server.

Harbor mounts this as a sidecar and declares it in task.toml:

    [[environment.mcp_servers]]
    name = "sandbox"
    transport = "streamable-http"
    url = "http://sandbox:8100/mcp"

It sits between the agent and the sandbox apps and does four things that
nothing else in the stack can:

1. Owns the session. The apps create state via a `login(seed)` tool and key it
   by session_id; every other tool takes that id. The facade logs in once at
   boot and injects the id, so `session_id` never appears in a published
   schema and never becomes a hackable surface.

2. Controls tool visibility. Harbor publishes whatever the MCP server exposes,
   so distractor count and presentation mode have to be decided here. Both
   become runtime config rather than authored content.

3. Writes an ordered environment trace. ATIF records what the agent saw; this
   records what the environment did -- status codes, gate rejections, which
   calls hit distractors.

4. Snapshots state for Harbor's [[verifier.collect]] hook, so the verifier
   never depends on the agent having called anything in particular.

The backends speak MCP, not HTTP. `login` returns the initial state and
`logout` returns the final state -- that is the sandbox's own contract, and
using it means no shim has to be bolted onto the fifteen apps.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastmcp import Client, FastMCP

from .catalog import Catalog, CatalogConfig, ToolSpec, sanitize_schema
from .trace import TraceWriter

log = logging.getLogger("facade")

LOGS = Path(os.environ.get("MCP_STUMP_LOGS", "/logs/artifacts"))
SESSIONS = Path(os.environ.get("MCP_STUMP_SESSIONS", "/tmp/mcp_stump_sessions.json"))
INITIAL_STATE = Path(os.environ.get("MCP_STUMP_INITIAL", "/logs/artifacts/initial_state.json"))

SYSTEM_APP = "LightSystem"


def _unwrap(result: Any) -> Any:
    """fastmcp returns a CallToolResult; get to the payload."""
    data = getattr(result, "structured_content", None)
    if data is None:
        content = getattr(result, "content", None)
        if content:
            text = getattr(content[0], "text", None)
            if text is not None:
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
        return result
    # fastmcp wraps bare returns under "result"
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


class Backend:
    """One sandbox app behind the facade."""

    def __init__(self, name: str, url: str, stateful: bool = True):
        self.name = name
        self.url = url
        self.stateful = stateful
        self.session_id: str | None = None
        self.tools: list[ToolSpec] = []

    def client(self) -> Client:
        # A fresh client per call: the sandbox apps are plain HTTP MCP servers
        # and holding sessions open across the whole trial proved fragile.
        return Client(self.url)

    async def list_tools(self) -> list[ToolSpec]:
        async with self.client() as c:
            tools = await c.list_tools()
        out: list[ToolSpec] = []
        for t in tools:
            if t.name in ("login", "logout", "_step", "_gen_past"):
                continue  # harness plumbing, never exposed to the agent
            out.append(
                ToolSpec(
                    server=self.name,
                    name=t.name,
                    description=t.description or "",
                    input_schema=t.inputSchema or {},
                )
            )
        self.tools = out
        return out

    async def login(self, seed: int, os_cfg: dict | None = None) -> Any:
        args: dict[str, Any] = {"seed": seed}
        if os_cfg is not None:
            args["os_cfg"] = os_cfg
        async with self.client() as c:
            info = _unwrap(await c.call_tool("login", args))
        self.session_id = info["session_id"]
        return info.get("session_info")

    async def logout(self) -> Any:
        """Returns the final state and tears the session down."""
        if not self.session_id:
            return None
        async with self.client() as c:
            return _unwrap(await c.call_tool("logout", {"session_id": self.session_id}))

    async def call(self, tool: str, args: dict) -> Any:
        payload = dict(args)
        if self.stateful and self.session_id:
            payload["session_id"] = self.session_id
        async with self.client() as c:
            return _unwrap(await c.call_tool(tool, payload))


class Facade:
    def __init__(self, config: CatalogConfig, backends: list[Backend], seed: int):
        self.config = config
        self.backends = {b.name: b for b in backends}
        self.seed = seed
        self.catalog: Catalog | None = None
        self.trace = TraceWriter(LOGS / "trace.jsonl")
        self._owner: dict[str, Backend] = {}

    # -- lifecycle ---------------------------------------------------------

    async def boot(self) -> None:
        """Log into every stateful app with the task seed, then build the catalog.

        LightSystem goes first: it is the shared virtual clock, and every other
        stateful app takes its session as `os_cfg` so timestamps stay coherent
        across apps.
        """
        specs: list[ToolSpec] = []
        initial: dict[str, Any] = {}

        system = self.backends.get(SYSTEM_APP)
        os_cfg = None
        if system is not None:
            initial[SYSTEM_APP] = await system.login(self.seed)
            os_cfg = {"session_id": system.session_id, "url": system.url}
            log.info("logged into %s session=%s", SYSTEM_APP, system.session_id)

        for backend in self.backends.values():
            if backend.stateful and backend.name != SYSTEM_APP:
                initial[backend.name] = await backend.login(self.seed, os_cfg)
                log.info("logged into %s session=%s", backend.name, backend.session_id)

            for spec in await backend.list_tools():
                specs.append(spec)
                self._owner.setdefault(spec.name, backend)
                self._owner[spec.qualified] = backend

        self.catalog = Catalog(specs, self.config)
        log.info("catalog ready: %s", self.catalog.stats())
        if self.catalog.collisions():
            log.info("renamed to avoid collisions: %s", self.catalog.collisions())

        self._persist_sessions()
        INITIAL_STATE.parent.mkdir(parents=True, exist_ok=True)
        INITIAL_STATE.write_text(json.dumps(initial, indent=2, default=str))

    def _persist_sessions(self) -> None:
        """So `dump` can snapshot even if this process has died."""
        SESSIONS.parent.mkdir(parents=True, exist_ok=True)
        SESSIONS.write_text(
            json.dumps(
                {
                    b.name: {"url": b.url, "session_id": b.session_id, "stateful": b.stateful}
                    for b in self.backends.values()
                },
                indent=2,
            )
        )

    async def snapshot(self) -> dict:
        out: dict[str, Any] = {}
        for backend in self.backends.values():
            if not backend.stateful:
                continue
            try:
                out[backend.name] = await backend.logout()
            except Exception as exc:  # noqa: BLE001
                out[backend.name] = {"__dump_error__": str(exc)}
        return out

    # -- dispatch ----------------------------------------------------------

    async def dispatch(self, name: str, args: dict) -> Any:
        started = time.time()
        assert self.catalog is not None

        spec = self.catalog.resolve(name)

        # Distractors have no implementation by design. Return a believable
        # refusal so probing them teaches the model nothing.
        if spec is None or spec.is_distractor:
            result = {"status": "failed",
                      "output": f"Tool '{name}' is not available in this environment."}
            self._record(name, args, result, started, distractor=True)
            return result

        backend = self._owner.get(spec.qualified) or self._owner.get(spec.name)
        if backend is None:
            result = {"status": "error", "output": f"No backend owns tool '{name}'."}
            self._record(name, args, result, started)
            return result

        try:
            result = await backend.call(spec.name, args)
        except Exception as exc:  # noqa: BLE001 - surfaced to the agent as a tool error
            result = {"status": "error", "output": str(exc)}

        self._record(name, args, result, started, server=backend.name)
        return result

    def _record(self, tool: str, args: dict, result: Any, started: float,
                *, server: str = "", distractor: bool = False) -> None:
        body = result if isinstance(result, dict) else {"output": result}
        self.trace.write({
            "server": server,
            "tool": tool,
            "args": args,
            "status": body.get("status", "ok"),
            "response": str(body.get("output", ""))[:2000],
            "latency_ms": int((time.time() - started) * 1000),
            "distractor": distractor,
        })


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------

def build(facade: Facade) -> FastMCP:
    mcp = FastMCP("mcp-stump-sandbox")

    if facade.config.presentation == "fetch":
        @mcp.tool()
        async def retrieve_tools(query: str, k: int = 20) -> list[dict]:
            """Find the tools most relevant to a described need."""
            assert facade.catalog is not None
            return [
                {"tool_name": t.qualified, "description": t.description,
                 "arguments": t.public_schema().get("properties", {})}
                for t in facade.catalog.visible(query)[:k]
            ]
        return mcp

    assert facade.catalog is not None
    for spec in facade.catalog.visible():
        _register(mcp, facade, spec)
    return mcp


def _register(mcp: FastMCP, facade: Facade, spec: ToolSpec) -> None:
    """Publish one sandbox tool, session_id stripped from its schema."""
    from fastmcp.tools import FunctionTool

    async def _handler(**kwargs: Any) -> Any:
        return await facade.dispatch(spec.qualified, kwargs)

    _handler.__name__ = spec.published
    _handler.__doc__ = spec.description

    # The API validates every published schema; one bad entry rejects the
    # whole tools array, so sanitise unconditionally rather than trusting the
    # source.
    mcp.add_tool(
        FunctionTool(
            fn=_handler,
            name=spec.published,
            description=spec.description or f"Tool {spec.published}.",
            parameters=sanitize_schema(spec.public_schema()),
        )
    )


def _load_backends() -> list[Backend]:
    """MCP_STUMP_BACKENDS='LightTalk=http://127.0.0.1:9001/mcp,math=http://127.0.0.1:8000/mcp:stateless'"""
    raw = os.environ.get("MCP_STUMP_BACKENDS", "")
    out: list[Backend] = []
    for chunk in filter(None, (c.strip() for c in raw.split(","))):
        name, _, rest = chunk.partition("=")
        stateless = rest.endswith(":stateless")
        url = rest.removesuffix(":stateless")
        out.append(Backend(name=name, url=url, stateful=not stateless))
    return out


def main() -> int:
    logging.basicConfig(level=os.environ.get("MCP_STUMP_LOG", "INFO"))

    seed = int(os.environ.get("MCP_STUMP_SEED", "0"))
    config = CatalogConfig(
        distractors=int(os.environ.get("MCP_STUMP_DISTRACTORS", "0")),
        presentation=os.environ.get("MCP_STUMP_PRESENTATION", "list_all"),
        window=int(os.environ.get("MCP_STUMP_WINDOW", "60")),
        seed=seed,
        distractor_registry=os.environ.get("MCP_STUMP_REGISTRY") or None,
    )

    facade = Facade(config, _load_backends(), seed)
    asyncio.run(facade.boot())

    mcp = build(facade)
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("MCP_STUMP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_STUMP_PORT", "8100")),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
