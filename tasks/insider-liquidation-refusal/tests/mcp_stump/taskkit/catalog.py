"""What can I build a task out of?

Forty-four apps and ~790 tools is past what an author can hold in their head,
and every failure this harness has had came from writing against a *remembered*
environment instead of the real one: a city with no flights, a product not in
the catalogue, `name=` where the tool wants `shop_name=`, a category that
existed on one seed and not another.

This indexes the sandbox statically -- `desc.json` for tool names, descriptions
and argument schemas; the source for gates and state shape -- so an author can
answer "what's available, what's gated, what can I assert on" before writing a
line of oracle.

Static on purpose: it needs no running sandbox, so it is cheap enough to
consult constantly. What it CANNOT tell you is what a given seed actually
contains -- whether a flight exists on a date, whether the catalogue stocks a
product. That is `mcp-stump preflight`, and the two are complementary: this one
says a capability exists, preflight says today's world has the data.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SANDBOX = Path("sandbox/software")

# Fallback only. Name prefixes cannot decide this: `conversations_history`,
# `auth_test`, `text_search` and `now` are pure reads that no prefix rule
# catches, while `add_review`, `mark_as_read` and `record_watch` genuinely
# mutate despite reading like queries. Whether a tool writes is decided by
# looking at what its implementation does -- see `_writers()`.
READ_PREFIXES = ("get_", "list_", "search_", "check_", "fuzzy_search_",
                 "find_", "query_", "read_", "show_", "describe_")

# In-place mutators on a collection reached from `self`.
MUTATORS = {"append", "extend", "insert", "pop", "remove", "clear",
            "update", "setdefault", "add", "discard", "sort", "reverse"}

# Not task material: session plumbing every app exposes.
PLUMBING = {"login", "logout", "uuid", "get_session_dict"}


@dataclass
class Tool:
    name: str
    description: str = ""
    args: dict = field(default_factory=dict)
    # None = undetermined, fall back to the name heuristic.
    mutates: bool | None = None

    @property
    def writes(self) -> bool:
        if self.mutates is not None:
            return self.mutates
        return not self.name.startswith(READ_PREFIXES)

    def signature(self) -> str:
        inner = ", ".join(sorted(self.args)) if self.args else ""
        return f"{self.name}({inner})"


@dataclass
class App:
    name: str
    tools: list[Tool] = field(default_factory=list)
    gates: list[str] = field(default_factory=list)
    gated_tools: list[str] = field(default_factory=list)
    state_keys: list[str] = field(default_factory=list)
    gradeable: bool = True

    @property
    def writers(self) -> list[Tool]:
        return [t for t in self.tools if t.writes]

    def find(self, needle: str) -> list[Tool]:
        n = needle.lower()
        return [t for t in self.tools
                if n in t.name.lower() or n in t.description.lower()]


def _state_keys(app_dir: Path) -> list[str]:
    """Top-level keys the app returns from get_session_dict.

    These are exactly the paths an authored check can assert on -- everything
    below `<App>.output.` in a collected dump. An app with no keys here cannot
    be graded on state at all, whatever else it does.

    Parsed with `ast`, not a regex: a regex over the return block captures keys
    of NESTED dicts too, which produced paths like `LightSlack.output.count`
    that look plausible, do not exist, and would fail only at run time.
    """
    keys: list[str] = []
    for f in app_dir.glob("*.py"):
        try:
            tree = ast.parse(f.read_text(errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != "get_session_dict":
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict):
                    keys += [k.value for k in sub.value.keys
                             if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                    break
    return sorted(set(keys))


def _gates(app_dir: Path) -> tuple[list[str], list[str]]:
    """(opener tools, tools sitting behind a gate).

    Two mechanisms in the corpus: `@require_*` decorators (LightStock's
    password / market-open / trade-quota / VIP stack, LightTalk's privilege),
    and bare `wait_*_password` openers. Both matter to an author because a
    gated tool is a free `hidden_prerequisite` -- the most reliable stump lever
    the harness has.
    """
    openers: set[str] = set()
    gated: set[str] = set()
    for f in app_dir.glob("*.py"):
        src = f.read_text(errors="ignore")
        openers |= set(re.findall(r"def (wait_\w+|ask_for_\w+|acc_\w+)\s*\(", src))
        # a decorated tool: capture the def that follows one or more @require_*
        for m in re.finditer(r"((?:\s*@require_\w+\n)+)\s*(?:async\s+)?def (\w+)", src):
            gated.add(m.group(2))
    return sorted(openers), sorted(gated)


def _touches_self(node: ast.AST) -> bool:
    """Does this expression reach back to `self`?"""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return isinstance(node, ast.Name) and node.id == "self"


def _writers(app_dir: Path) -> dict[str, bool]:
    """method name -> does it mutate session state?

    A tool writes if its implementation assigns to, deletes from, or calls an
    in-place mutator on something rooted at `self` -- or on a local that was
    bound from `self`. `chat_post_message` appends to `self.messages`;
    `conversations_history` only filters it.

    Getting this wrong matters most for refusal tasks: their forbidden-tool
    list is derived from this, and listing a READ there fails a correct refusal
    (which reads before declining), while missing a WRITE passes a model that
    complied.
    """
    out: dict[str, bool] = {}
    calls: dict[str, set[str]] = {}
    for f in app_dir.glob("*.py"):
        try:
            tree = ast.parse(f.read_text(errors="ignore"))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Locals that alias live session state. Three bindings matter, and
            # the corpus uses all three:
            #   contact = self.contacts[uid]          direct attribute
            #   contact, err = self.__get_contact(u)  private getter -- the
            #     dominant pattern here, and the one a naive check misses:
            #     mark_as_read mutates `contact.read_new_message`, never
            #     touching `self.` in the statement that writes
            #   for c in self.contacts: ...           loop variable
            aliases: set[str] = set()
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign):
                    src_touches = _touches_self(n.value) or (
                        isinstance(n.value, ast.Call) and _touches_self(n.value.func))
                    if not src_touches:
                        continue
                    for t in n.targets:
                        if isinstance(t, ast.Name):
                            aliases.add(t.id)
                        elif isinstance(t, (ast.Tuple, ast.List)):
                            aliases |= {e.id for e in t.elts if isinstance(e, ast.Name)}
                elif isinstance(n, ast.For) and (
                        _touches_self(n.iter)
                        or (isinstance(n.iter, ast.Call) and _touches_self(n.iter.func))):
                    if isinstance(n.target, ast.Name):
                        aliases.add(n.target.id)

            # A local that is RETURNED is a response object the method built,
            # not live session state, so reshaping it is not a write.
            # `get_last_k_moments` does `result = self.get_all_moments(...)`
            # then trims `result["output"]` before returning it -- counting
            # that as a mutation put three read-only getters on a refusal
            # task's forbidden list, which would fail an agent for merely
            # looking before it declined.
            returned = {r.value.id for r in ast.walk(fn)
                        if isinstance(r, ast.Return) and isinstance(r.value, ast.Name)}
            aliases -= returned

            def roots(node: ast.AST) -> bool:
                if _touches_self(node):
                    return True
                base = node
                while isinstance(base, (ast.Attribute, ast.Subscript)):
                    base = base.value
                return isinstance(base, ast.Name) and base.id in aliases

            mutates = False
            for n in ast.walk(fn):
                if isinstance(n, (ast.Assign, ast.AugAssign)):
                    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                    if any(isinstance(t, (ast.Attribute, ast.Subscript)) and roots(t)
                           for t in targets):
                        mutates = True
                elif isinstance(n, ast.Delete):
                    if any(roots(t) for t in n.targets):
                        mutates = True
                elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                    if n.func.attr in MUTATORS and roots(n.func.value):
                        mutates = True
                if mutates:
                    break
            # A tool defined in app.py that only delegates is judged by the
            # method it delegates to, so keep the strongest signal seen.
            out[fn.name] = out.get(fn.name, False) or mutates
            calls.setdefault(fn.name, set()).update(
                n.func.attr for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "self")

    # Propagate through delegation to a fixpoint. `send_image` writes nothing
    # itself -- it calls `self.send_message(...)`, which does. A wrapper is the
    # obvious way to do a forbidden thing while avoiding the obvious tool name,
    # so a refusal task whose forbidden list misses it has a hole exactly where
    # it matters.
    changed = True
    while changed:
        changed = False
        for name, callees in calls.items():
            if not out.get(name) and any(out.get(c) for c in callees):
                out[name] = True
                changed = True
    return out


def load_app(app_dir: Path) -> App:
    tools: list[Tool] = []
    desc = app_dir / "desc.json"
    if desc.is_file():
        try:
            for e in json.loads(desc.read_text()):
                n = e.get("tool_name", "")
                if n and n not in PLUMBING:
                    tools.append(Tool(n, e.get("description", ""),
                                      e.get("arguments", {}) or {}))
        except (json.JSONDecodeError, TypeError):
            pass
    if not tools:  # fall back to the source when desc.json is absent/broken
        src = (app_dir / "app.py").read_text(errors="ignore")
        for m in re.finditer(r"@mcp\.tool\s*(?:\(.*?\))?\s*\n\s*(?:async\s+)?def (\w+)\(([^)]*)\)",
                             src, re.S):
            n = m.group(1)
            if n in PLUMBING:
                continue
            args = {a.split(":")[0].strip(): {} for a in m.group(2).split(",")
                    if a.strip() and "session_id" not in a}
            tools.append(Tool(n, "", args))

    mut = _writers(app_dir)
    for t in tools:
        if t.name in mut:
            t.mutates = mut[t.name]

    openers, gated = _gates(app_dir)
    keys = _state_keys(app_dir)
    app_src = (app_dir / "app.py").read_text(errors="ignore")
    i = app_src.find("async def logout")
    body = app_src[i:i + 900] if i >= 0 else ""
    gradeable = bool(re.search(
        r'"output"\s*:\s*(session_info|session\.\w+\.get_session_dict\(\))', body))

    return App(name=app_dir.name, tools=sorted(tools, key=lambda t: t.name),
               gates=openers, gated_tools=gated, state_keys=keys,
               gradeable=gradeable)


def load(root: Path = SANDBOX) -> dict[str, App]:
    return {d.name: load_app(d)
            for d in sorted(Path(root).iterdir())
            if d.is_dir() and (d / "app.py").is_file()}


# --------------------------------------------------------------------------
# lever affordances -- what each app can actually be used to test
# --------------------------------------------------------------------------

def affordances(app: App) -> list[str]:
    """Which stump levers this app can support, from what it exposes."""
    out: list[str] = []
    if app.gates or app.gated_tools:
        out.append("hidden_prerequisite")
    if any("acc_network" in g or "network" in g for g in app.gates):
        out.append("transient_failure")
    if app.state_keys:
        out.append("dirty_state")
    if len(app.writers) >= 3:
        out.append("long_chain")
    names = " ".join(t.name for t in app.tools)
    if "fuzzy_search" in names:
        out.append("referential_ambiguity")
    return out
