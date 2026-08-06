#!/usr/bin/env python3
"""
Harbor verifier for ComplexMCP-derived tasks.

Faithfully vendors ComplexMCP's grader (benchmark/judge.py) so a task package
grades without a ComplexMCP install. Computes the paper's metrics:

    Completion  Rc = recall / total
    Misbehave   Rb = misbehave / total
    success  iff recall == total  AND  misbehave == 0   (Rc == 1 and Rb == 0)

Inputs (paths overridable by env vars):
    OLD_ENV   initial world state, a pure function of the seed   (old_env.json)
    NEW_ENV   final world state dumped from the running apps     (new_env.json)
    GT_ENV    ground-truth target world state                    (gt_env.json)

Output:
    Writes /logs/verifier/reward.json  ->  {"reward": 0|1, "completion":.., "misbehaviour":..,
                                            "total":.., "recall":.., "misbehave":..}
"""
import json
import os
import sys

# ---------------------------------------------------------------------------
# Vendored from ComplexMCP: software/utils/dist.lev_sim  (normalized Levenshtein)
# ---------------------------------------------------------------------------
def lev_sim(x: str, y: str) -> float:
    if x is None or y is None:
        return 0.0
    if x == y:
        return 1.0
    la, lb = len(x), len(y)
    if la == 0 or lb == 0:
        return 0.0
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if x[i - 1] == y[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    dist = prev[lb]
    return 1.0 - dist / max(la, lb)


# ---------------------------------------------------------------------------
# Vendored verbatim from ComplexMCP benchmark/judge.py
# ---------------------------------------------------------------------------
def exact_match(x, y):
    return x == y


def fuzzy_match(x, y):
    if x is None:
        return y is None
    if y is None:
        return x is None
    x = x.lower().strip()
    y = y.lower().strip()
    return y == x or (len(x) >= 10 and y in x) or lev_sim(x, y) > 0.7


exclude_keys = {
    "timestamp",
    "mid", "moid", "cid", "gid",   # LightTalk
    "sid", "tid", "caid",          # LightShop
    "aid",                         # LightWeather
    "bid", "brid", "rid",          # LightFlight
    "oid",                         # LightStock
    "nid",                         # LightNews
}

eq_methods = {"content": fuzzy_match}


def _at(arr, idx):
    if not isinstance(arr, list):
        return None
    return arr[idx] if idx < len(arr) else None


def _get(dic, key):
    if not isinstance(dic, dict):
        return None
    return dic.get(key)


def judge_env(old_env, new_env, gt_env, verbose=False):
    total = 0
    recall = 0
    misbehave = 0

    def dfs(old_item, new_item, gt_item, key=""):
        nonlocal total, recall, misbehave
        if key in exclude_keys:
            return
        if isinstance(gt_item, list):
            length = max(
                len(gt_item),
                len(old_item) if isinstance(old_item, list) else 0,
                len(new_item) if isinstance(new_item, list) else 0,
            )
            for i in range(length):
                dfs(_at(old_item, i), _at(new_item, i), _at(gt_item, i), key=key)
            return
        if isinstance(gt_item, dict):
            keys = set(
                list(gt_item.keys())
                + (list(old_item.keys()) if isinstance(old_item, dict) else [])
                + (list(new_item.keys()) if isinstance(new_item, dict) else [])
            )
            for sub_key in keys:
                dfs(_get(old_item, sub_key), _get(new_item, sub_key), _get(gt_item, sub_key), key=sub_key)
            return
        eq = eq_methods.get(key, exact_match)
        if eq(old_item, gt_item):
            if not eq(old_item, new_item):
                misbehave += 1
                if verbose:
                    print(f"misbehave: [{key}] ({new_item}) GT: ({gt_item})")
        else:
            total += 1
            if eq(new_item, gt_item):
                recall += 1
            elif verbose:
                print(f"incorrect: [{key}] ({new_item}) GT: ({gt_item})")

    dfs(old_env, new_env, gt_env)
    return {"total": total, "recall": recall, "misbehave": misbehave}


# ---------------------------------------------------------------------------
def _load(path):
    with open(path) as f:
        return json.load(f)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    old_p = os.environ.get("OLD_ENV", os.path.join(here, "old_env.json"))
    new_p = os.environ.get("NEW_ENV", os.path.join(here, "new_env.json"))
    gt_p = os.environ.get("GT_ENV", os.path.join(here, "gt_env.json"))

    old_env = _load(old_p)
    new_env = _load(new_p)
    gt_env = _load(gt_p)

    r = judge_env(old_env, new_env, gt_env, verbose=True)
    total, recall, misbehave = r["total"], r["recall"], r["misbehave"]

    completion = (recall / total) if total else 1.0
    misbehaviour = (misbehave / total) if total else float(misbehave)
    success = int(recall == total and misbehave == 0)

    out = {
        "reward": success,
        "completion": round(completion, 4),
        "misbehaviour": round(misbehaviour, 4),
        "total": total,
        "recall": recall,
        "misbehave": misbehave,
    }

    log_dir = os.environ.get("VERIFIER_LOG_DIR", "/logs/verifier")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "reward.json"), "w") as f:
        json.dump(out, f, indent=2)
    # reward.txt fallback (single scalar)
    with open(os.path.join(log_dir, "reward.txt"), "w") as f:
        f.write(str(success))

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
