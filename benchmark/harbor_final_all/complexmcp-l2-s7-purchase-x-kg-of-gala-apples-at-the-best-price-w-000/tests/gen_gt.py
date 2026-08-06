#!/usr/bin/env python3
"""
Ground-truth scaffold for this ComplexMCP task.

Task: Purchase x kg of Gala apples at the best price, where x equals the total number of your immediate and extended

gt_env.json (and old_env.json) are seed-generated world snapshots that only
the ComplexMCP runtime can produce. This task's target world state is obtained
by replaying the reference trajectory (solution/trajectory.json) against the
seeded runtime and dumping the result (see GT_GENERATION.md). Because the exact
state mutation is task-specific, this generator does NOT hand-fabricate the
target; it takes the runtime-produced target dump and emits gt_env.json,
validating that it is well-formed and (optionally) that it actually differs
from old_env so the diff-based judge has something to score.

Usage:
    # after capturing the post-trajectory dump as target_env.json:
    python3 gen_gt.py target_env.json gt_env.json [--old-env old_env.json]
"""
import argparse
import json
import sys


def _load(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('target_env',
                    help='runtime dump AFTER replaying solution/trajectory.json')
    ap.add_argument('gt_env', help='output ground-truth path to write')
    ap.add_argument('--old-env', default=None,
                    help='initial dump; if given, assert gt differs from it')
    args = ap.parse_args()

    target = _load(args.target_env)
    if not isinstance(target, (dict, list)):
        raise SystemExit('target_env must be a JSON object or array')

    if args.old_env is not None:
        old = _load(args.old_env)
        if json.dumps(old, sort_keys=True, ensure_ascii=False) == \
           json.dumps(target, sort_keys=True, ensure_ascii=False):
            print('WARNING: target_env is identical to old_env — the judge will '
                  'score nothing (total=0). Did the trajectory replay run?',
                  file=sys.stderr)

    with open(args.gt_env, 'w', encoding='utf-8') as f:
        json.dump(target, f, ensure_ascii=False)
    print(f'wrote {args.gt_env} from {args.target_env}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
