"""State snapshot for Harbor's [[verifier.collect]] hook.

    [[verifier.collect]]
    service = "sandbox"
    command = "python -m mcp_stump.facade.dump > /tmp/final_state.json"
    timeout_sec = 60.0

    artifacts = [{ source = "/tmp/final_state.json", service = "sandbox" }]

Runs inside the sandbox sidecar after the agent phase ends and writes the full
per-app state to stdout. Harbor copies the file out for grading.

Deliberately a separate process from the facade: it reads the session ids the
facade persisted at boot and talks to the apps directly. If the facade has
crashed, the snapshot still succeeds -- which is what stops a dead agent run
from being scored as a verifier failure.

`logout` is the sandbox's own state-return contract, so no shim is needed.
Sidecar collect commands run under POSIX `sh -c`, not bash.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from fastmcp import Client

SESSIONS = Path(os.environ.get("MCP_STUMP_SESSIONS", "/tmp/mcp_stump_sessions.json"))


def _unwrap(result: Any) -> Any:
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
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


async def snapshot(sessions: dict[str, dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, info in sessions.items():
        if not info.get("stateful", True) or not info.get("session_id"):
            continue
        try:
            async with Client(info["url"]) as c:
                out[name] = _unwrap(
                    await c.call_tool("logout", {"session_id": info["session_id"]})
                )
        except Exception as exc:  # noqa: BLE001
            # Record in-band rather than aborting: a partial snapshot still
            # scores every app that did respond.
            out[name] = {"__dump_error__": str(exc)}
            print(f"dump failed for {name}: {exc}", file=sys.stderr)
    return out


def main() -> int:
    if not SESSIONS.exists():
        print(f"no session file at {SESSIONS}", file=sys.stderr)
        print("{}")
        return 1

    sessions = json.loads(SESSIONS.read_text())
    state = asyncio.run(snapshot(sessions))
    json.dump(state, sys.stdout, indent=2, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
