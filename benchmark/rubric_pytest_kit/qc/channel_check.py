#!/usr/bin/env python3
"""QC gate: channel separation, scoped to the TEST FUNCTION BODIES only.

The fixed template header (dump()/old_env()/find()/added() etc.) is the sanctioned
Channel-A data layer and is exempt. Inside `def test_*` functions, pytest may read
world state ONLY through those accessors — never a file the AGENT wrote (output.md,
trajectory.json), never glob discovery, never message/format quality.

Checks per test function:
  * forbidden file reads/discovery: open(, .read_text(, csv.reader, glob, output.md,
    trajectory.json  (the header's dump()/old_env() are the only legal readers)
  * Convention-B polarity: no `assert not`, `assert ... == 0`, `is None`, `not in`
    inside an `assert` statement (encode absence as positive assert + negative weight)
  * subjective adjectives (belong in the rubric)

Exit 0 pass, 1 fail, 2 usage error."""
import ast
import re
import sys

FORBIDDEN_READS = [r"output\.md", r"trajectory\.json", r"\bglob\b", r"\.read_text\(",
                   r"csv\.reader", r"\bopen\(", r"json\.load\(open\("]
SUBJECTIVE = [r"\bhelpful\b", r"\bpolite\b", r"\bthorough\b", r"\bclear(ly)?\b",
              r"\bgood\b", r"\breasonable\b", r"\bappropriate\b", r"\binformative\b"]
POLARITY = [r"\bassert\s+not\b", r"==\s*0\b", r"len\([^)]*\)\s*==\s*0",
            r"\bis\s+None\b", r"\bnot\s+in\b"]


def main(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    tests = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    hits = []
    for fn in tests:
        body_src = ast.get_source_segment(src, fn) or ""
        for i, line in enumerate(body_src.splitlines(), fn.lineno):
            stripped = line.strip()
            for p in FORBIDDEN_READS:
                if re.search(p, line):
                    hits.append((i, "file-read/discovery", p, stripped))
            for p in SUBJECTIVE:
                if re.search(p, line):
                    hits.append((i, "subjective adjective (belongs in rubric)", p, stripped))
            if stripped.startswith("assert"):
                for p in POLARITY:
                    if re.search(p, line):
                        hits.append((i, "negative-polarity (use positive assert + negative weight)",
                                     p, stripped))
    if hits:
        print("FAIL channel_check:")
        for ln, label, pat, text in hits:
            print(f"  line {ln} [{label}] /{pat}/ :: {text}")
        return 1
    print(f"PASS channel_check: {len(tests)} test bodies read only the dump+baseline; polarity clean")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: channel_check.py <test_outputs.py>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
