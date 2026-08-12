"""Re-arm the seed architecture across all apps, behind a runtime toggle.

Each app's session __init__ was replaced by `restore_into(self, world.pkl)` when
the harness went seedless. The original seed-based __init__ still exists in git,
and the generation methods (init_shops, ...) were never removed. This tool, per
app session file:

  1. finds the __init__ that calls restore_into (the seedless one),
  2. recovers the original seed-based __init__ from git (the commit that first
     introduced restore_into to that file, minus one),
  3. rewrites __init__ to branch:
         if seed_mode(): <original seed body>
         else:           <current seedless body>
  4. ensures `seed_mode, resolve_seed` are imported.

Default behaviour is unchanged (seedless); COMPLEXMCP_SEED_MODE=generate opts in.

Extraction is AST-based (line spans), so bodies are spliced verbatim and
re-indented, never regex-mangled. Files it cannot confidently handle are skipped
and reported rather than corrupted.

    python -m benchmark.migrate_seed_toggle --dry     # report only
    python -m benchmark.migrate_seed_toggle --apply   # write changes
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True)


def session_files():
    out = sh("git", "grep", "-l", "restore_into", "--", "software/").stdout
    return [f for f in out.splitlines() if f.endswith(".py")]


def _init_calls_restore(func, src_lines):
    span = "\n".join(src_lines[func.lineno - 1: func.end_lineno])
    return "restore_into" in span


def find_init(tree, src_lines, *, require_restore):
    """Return (ClassDef, __init__ FunctionDef) or None."""
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for item in cls.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                if not require_restore or _init_calls_restore(item, src_lines):
                    return cls, item
    return None


def _func_end(func):
    ends = [getattr(s, "end_lineno", None) or getattr(s, "lineno", None)
            for s in ast.walk(func)]
    return max(e for e in ends if e)


def body_span(func, src_lines):
    first = func.body[0].lineno - 1
    return src_lines[first:_func_end(func)]


def sig_span(func, src_lines):
    return src_lines[func.lineno - 1: func.body[0].lineno - 1]


def reindent(lines, spaces):
    block = textwrap.dedent("\n".join(lines))
    pad = " " * spaces
    return "\n".join((pad + ln) if ln.strip() else "" for ln in block.splitlines())


def first_restore_commit(path):
    # oldest commit that changed the count of "restore_into" in this file
    out = sh("git", "log", "--reverse", "-S", "restore_into",
             "--format=%H", "--", path).stdout.split()
    return out[0] if out else None


def old_source(path):
    commit = first_restore_commit(path)
    if not commit:
        return None
    par = sh("git", "rev-parse", f"{commit}^").stdout.strip()
    if not par:
        return None
    r = sh("git", "show", f"{par}:{path}")
    return r.stdout if r.returncode == 0 and r.stdout else None


def migrate(path):
    """Return (new_text, note) or (None, reason)."""
    cur = open(path, encoding="utf-8").read()
    if "seed_mode(" in cur:
        return None, "already migrated"
    cur_lines = cur.splitlines()
    try:
        cur_tree = ast.parse(cur)
    except SyntaxError as e:
        return None, f"current unparseable: {e}"

    hit = find_init(cur_tree, cur_lines, require_restore=True)
    if not hit:
        return None, "no __init__ calls restore_into"
    cur_cls, cur_init = hit

    old = old_source(path)
    if not old:
        return None, "no pre-restore version in git"
    old_lines = old.splitlines()
    try:
        old_tree = ast.parse(old)
    except SyntaxError as e:
        return None, f"old unparseable: {e}"

    old_hit = None
    for cls in [n for n in ast.walk(old_tree) if isinstance(n, ast.ClassDef)]:
        if cls.name == cur_cls.name:
            for item in cls.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    old_hit = (cls, item)
    if not old_hit:
        return None, f"no seed __init__ for class {cur_cls.name} in git"
    old_init = old_hit[1]

    base = len(cur_lines[cur_init.lineno - 1]) - len(cur_lines[cur_init.lineno - 1].lstrip())
    sig = sig_span(cur_init, cur_lines)
    cur_body = body_span(cur_init, cur_lines)
    old_body = body_span(old_init, old_lines)

    pad = " " * base
    block = list(sig)
    block.append(f"{pad}    if seed_mode():")
    block.append(f"{pad}        # Seed architecture: world rolled from a seed (re-armed).")
    block.append(reindent(old_body, base + 8))
    block.append(f"{pad}    else:")
    block.append(f"{pad}        # Seedless: world loaded verbatim from the frozen snapshot.")
    block.append(reindent(cur_body, base + 8))

    new_lines = (cur_lines[:cur_init.lineno - 1] + block
                 + cur_lines[_func_end(cur_init):])
    new_text = "\n".join(new_lines) + ("\n" if cur.endswith("\n") else "")

    # ensure the toggle helpers are imported
    if "seed_mode" not in new_text.split("class ")[0]:
        lines = new_text.splitlines()
        for i, ln in enumerate(lines):
            if "world_snapshot import" in ln and "seed_mode" not in ln:
                lines[i] = ln.rstrip() + ", seed_mode, resolve_seed"
                break
        new_text = "\n".join(lines) + "\n"

    try:
        ast.parse(new_text)
    except SyntaxError as e:
        return None, f"RESULT unparseable (skipped): {e}"
    return new_text, f"class {cur_cls.name}"


def main():
    apply = "--apply" in sys.argv
    files = session_files()
    ok = skip = 0
    skipped = []
    for f in files:
        new_text, note = migrate(f)
        if new_text is None:
            skip += 1
            skipped.append((f, note))
            continue
        ok += 1
        if apply:
            open(f, "w", encoding="utf-8").write(new_text)
    print(f"{'APPLIED' if apply else 'DRY-RUN'}: {ok} migrated, {skip} skipped, "
          f"{len(files)} total")
    for f, why in skipped:
        print(f"  skip  {f}  -- {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
