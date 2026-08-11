#!/usr/bin/env python3
"""Discover Equal Function Sets for the complex-mcp sandbox.

    scripts/build_efs.py --out registry/efs.json [--cross-server] [--dry-run]

Reads the sandbox tool descriptions, generates candidate pairs, asks a model to
verify each one against the oracle's real usage where available, and writes the
Union-Find grouping.

Verification goes through ccbridge (Claude Code OAuth), same as trial runs. The
``--dry-run`` path only lists candidate pairs and needs no network or creds.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.efs import (  # noqa: E402
    EFSIndex, Tool, candidates, group, resolve_for_trace, verify_pair,
)

BRIDGE = os.environ.get("CCBRIDGE_URL", "http://127.0.0.1:8765")
MODEL = os.environ.get("MCP_STUMP_EFS_MODEL", "claude-sonnet-4-5-20250929")


def load_tools(root: Path) -> list[Tool]:
    """Load every tool from the per-app ``software/*/desc.json`` files.

    Each desc.json is a list of ``{tool_name, description, arguments, returns}``;
    ``arguments`` is a dict keyed by argument name. ``session_id`` is dropped so
    that a tool's argument shape reflects what the caller actually chooses.
    """
    out: list[Tool] = []
    for f in sorted(glob.glob(str(root / "software/*/desc.json"))):
        app = Path(f).parent.name
        for t in json.load(open(f)):
            args = t.get("arguments") or {}
            out.append(Tool(
                server=app,
                name=t["tool_name"],
                description=t.get("description", ""),
                args=tuple(a for a in args if a != "session_id"),
            ))
    return out


def load_gold_traces(paths: list[str]) -> list[dict]:
    """Every oracle call across the given traces, de-duplicated by tool.

    Equivalence is verified against a real step, so a trace is required. With
    no trace the question degenerates to "are these tools identical in
    general", which is a different (and much stricter) question -- it rejects
    search/fuzzy_search and every other real equivalence.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for pattern in paths:
        for f in sorted(glob.glob(pattern)):
            for line in open(f):
                r = json.loads(line)
                if r.get("status") != "ok":
                    continue
                t = str(r.get("tool", ""))
                if t in seen:
                    continue
                seen.add(t)
                out.append(r)
    return out


def make_asker(secret: str):
    import httpx

    client = httpx.Client(timeout=120.0)

    def ask(prompt: str) -> str:
        r = client.post(
            f"{BRIDGE}/v1/messages",
            headers={"content-type": "application/json", "x-api-key": secret,
                     "anthropic-version": "2023-06-01"},
            json={"model": MODEL, "max_tokens": 300,
                  "messages": [{"role": "user", "content": prompt}]},
        )
        r.raise_for_status()
        blocks = r.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks)

    return ask


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sandbox", type=Path, default=_REPO_ROOT,
                    help="Repo root holding software/*/desc.json (default: the "
                         "complex-mcp checkout).")
    ap.add_argument("--out", type=Path, default=_REPO_ROOT / "registry/efs.json")
    ap.add_argument("--cross-server", action="store_true",
                    help="Also consider pairs across apps (off by default: "
                         "LightShop::check_balance and LightFlight::check_balance "
                         "are lexically identical and semantically unrelated).")
    ap.add_argument("--dry-run", action="store_true", help="List candidates, do not verify.")
    ap.add_argument("--traces", nargs="*",
                    default=[str(_REPO_ROOT / "out/trials_*/controls/oracle/trace.jsonl")],
                    help="Gold traces supplying the step context for verification.")
    args = ap.parse_args()

    tools = load_tools(args.sandbox)
    pairs = candidates(tools, cross_server=args.cross_server)
    print(f"{len(tools)} tools -> {len(pairs)} candidate pairs")

    if args.dry_run:
        for a, b in pairs:
            print(f"  {a.id:<38} ~ {b.id}")
        return 0

    secret_file = Path("/tmp/ccbridge.secret")
    secret = secret_file.read_text().strip() if secret_file.is_file() else "stub"
    ask = make_asker(secret)
    gold = load_gold_traces(args.traces)
    if not gold:
        print("no gold traces found; run a task first so equivalence has a step "
              "to be verified against", file=sys.stderr)
        return 1
    print(f"{len(gold)} distinct oracle steps supply the verification context\n")

    def report(a, b, ok, why):
        print(f"  {'SATISFIES ' if ok else 'distinct  '}  {a.name} ~ {b.name}")
        print(f"                {why[:105]}")

    index, audit = resolve_for_trace(gold, tools, ask,
                                     cross_server=args.cross_server,
                                     on_result=report)
    index.save(args.out)
    Path(args.out).with_suffix(".audit.json").write_text(json.dumps(audit, indent=1))

    ok = sum(1 for a in audit if a["satisfies"])
    print(f"\nverified {ok} / {len(audit)} step-scoped pairs")
    print(f"-> {len(index.sets)} sets covering {sum(len(s) for s in index.sets)} tools")
    for s in index.sets:
        print("   ", sorted(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
