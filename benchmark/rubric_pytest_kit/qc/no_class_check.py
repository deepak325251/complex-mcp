#!/usr/bin/env python3
"""QC gate: test_outputs.py must be FLAT `def test_*` functions — zero classes,
no fixtures, no conftest. Exit 0 pass, 1 fail, 2 usage error."""
import ast
import sys


def main(path):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bad.append(f"class {node.name} (line {node.lineno})")
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            for d in node.decorator_list:
                bad.append(f"decorator on {node.name} (line {node.lineno}) — no fixtures/marks")
    n_tests = sum(1 for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name.startswith("test_"))
    if bad:
        print("FAIL no_class_check:")
        for b in bad:
            print("  -", b)
        return 1
    if n_tests == 0:
        print("FAIL no_class_check: no top-level test_ functions found")
        return 1
    print(f"PASS no_class_check: {n_tests} flat test_ functions, 0 classes")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: no_class_check.py <test_outputs.py>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
