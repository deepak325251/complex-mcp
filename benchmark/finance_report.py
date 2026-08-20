"""Finance API reporter — one usage record per trajectory.

POSTs to the Odoo Finance API endpoint
    POST <FINANCE_API_URL>/ethara_project/trajectory_usage/create
after each trajectory (attempt) finishes grading. Reporting is a side channel:
it is a no-op unless FINANCE_API_URL is set, and it NEVER raises — a Finance
API outage must not fail a benchmark run.

Configuration (environment):
    FINANCE_API_URL          base URL, e.g. https://odoo.example.com/api/v1
                             (the endpoint path is appended if not present).
                             Unset -> reporting disabled.
    FINANCE_API_KEY          auth credential. Sent as `Authorization: Bearer <key>`
                             unless FINANCE_API_AUTH_HEADER names another header,
                             in which case the raw key is sent under that header.
    FINANCE_API_AUTH_HEADER  optional header name override (e.g. "api-key").
    FINANCE_PROJECT_ID       e.g. "PRJ-512"          (default "complex-mcp")
    FINANCE_PROJECT_TYPE     e.g. "Technical"        (default "Technical")
    FINANCE_TEAM_TYPE        e.g. "Projects"         (default "Projects")
    FINANCE_SUBSCRIPTION_ID  e.g. "SUB-98765"        (default "")
    FINANCE_BUDGET_TYPE      "RFP" | "Production"    (default "RFP")
    FINANCE_RFP_SUB_TYPE     "Testing" | "Sampling"  (default "Testing"; RFP only)
    FINANCE_PRODUCTION_MODE  "Singlephase" | "Multiphase"
                             (default "Singlephase"; Production only)

The four budget variations are mutually exclusive; this module enforces the
API's consistency rules (RFP leaves production_mode empty and vice versa,
is_phase_based true only for Multiphase) regardless of stray env values.

Token mapping: the agent reports Anthropic-style usage (uncached input, output,
cache_read, cache_creation). The Finance API's *_input_cache_tokens carries
cache_read and *_output_cache_tokens carries cache_creation — both are
input-side in Anthropic terms, but this keeps every bucket visible upstream.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

ENDPOINT_PATH = "/ethara_project/trajectory_usage/create"

_disabled_warned = False
# id(judge) -> last-reported cumulative totals, so each trajectory reports
# only the judge tokens IT spent (the judge closure is per-process).
_judge_snapshots = {}

_JUDGE_KEYS = ("input_tokens", "output_tokens",
               "cache_read_tokens", "cache_creation_tokens", "cost_usd")


def _endpoint():
    url = (os.environ.get("FINANCE_API_URL") or "").strip().rstrip("/")
    if not url:
        return None
    if not url.endswith(ENDPOINT_PATH):
        url += ENDPOINT_PATH
    return url


def _budget_fields():
    budget_type = os.environ.get("FINANCE_BUDGET_TYPE", "RFP").strip() or "RFP"
    if budget_type.lower() == "production":
        mode = os.environ.get("FINANCE_PRODUCTION_MODE", "Singlephase").strip()
        mode = "Multiphase" if mode.lower() == "multiphase" else "Singlephase"
        return {"budget_type": "Production", "rfp_sub_type": "",
                "production_mode": mode,
                "is_phase_based": mode == "Multiphase"}
    sub = os.environ.get("FINANCE_RFP_SUB_TYPE", "Testing").strip()
    sub = "Sampling" if sub.lower() == "sampling" else "Testing"
    return {"budget_type": "RFP", "rfp_sub_type": sub,
            "production_mode": "", "is_phase_based": False}


def judge_usage_delta(judge):
    """Return this trajectory's judge_lines from the judge closure's cumulative
    `usage` counter (attached by make_*_rubric_judge). Advances the snapshot so
    the next call reports only new spend. [] when there is no judge / no spend.
    """
    totals = getattr(judge, "usage", None)
    if not isinstance(totals, dict):
        return []
    prev = _judge_snapshots.get(id(judge), {})
    delta = {k: (totals.get(k, 0) or 0) - (prev.get(k, 0) or 0)
             for k in _JUDGE_KEYS}
    _judge_snapshots[id(judge)] = {k: totals.get(k, 0) or 0 for k in _JUDGE_KEYS}
    if not any(delta.values()):
        return []
    return [{
        "model_name": totals.get("model_name", ""),
        "judge_input_tokens": delta["input_tokens"],
        "judge_output_tokens": delta["output_tokens"],
        "judge_input_cache_tokens": delta["cache_read_tokens"],
        "judge_output_cache_tokens": delta["cache_creation_tokens"],
        "judge_cost_usd": round(delta["cost_usd"], 6),
    }]


def build_payload(record, model, task_name, judge_lines=None):
    usage = record.get("usage") or {}
    payload = {
        "project_id": os.environ.get("FINANCE_PROJECT_ID", "complex-mcp"),
        "project_type": os.environ.get("FINANCE_PROJECT_TYPE", "Technical"),
        "task_id": str(task_name),
        "trajectory_id": record.get("session_id") or "",
        "team_type": os.environ.get("FINANCE_TEAM_TYPE", "Projects"),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model_name": model,
        "trajectory_input_tokens": usage.get("input_tokens", 0) or 0,
        "trajectory_output_tokens": usage.get("output_tokens", 0) or 0,
        "trajectory_input_cache_tokens": usage.get("cache_read_tokens", 0) or 0,
        "trajectory_output_cache_tokens": usage.get("cache_creation_tokens", 0) or 0,
        "trajectory_cost_usd": usage.get("cost_usd", 0.0) or 0.0,
        "subscription_id": os.environ.get("FINANCE_SUBSCRIPTION_ID", ""),
        "judge_lines": judge_lines or [],
    }
    payload.update(_budget_fields())
    return payload


def report_trajectory_usage(record, model, task_name, rubric_judge=None):
    """Fire-and-forget POST of one trajectory's usage. Never raises."""
    global _disabled_warned
    try:
        # Always advance the judge snapshot, even when reporting is disabled,
        # so enabling mid-run doesn't attribute the whole backlog to one task.
        judge_lines = judge_usage_delta(rubric_judge)
        endpoint = _endpoint()
        if endpoint is None:
            if not _disabled_warned:
                _disabled_warned = True
                print("[finance] FINANCE_API_URL not set -- usage reporting "
                      "disabled (prints once per process)")
            return None
        payload = build_payload(record, model, task_name, judge_lines)
        headers = {"Content-Type": "application/json"}
        key = os.environ.get("FINANCE_API_KEY")
        if key:
            hdr = os.environ.get("FINANCE_API_AUTH_HEADER") or "Authorization"
            headers[hdr] = key if hdr.lower() != "authorization" else f"Bearer {key}"
        req = urllib.request.Request(
            endpoint, data=json.dumps(payload).encode(), method="POST",
            headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body = resp.read().decode(errors="replace")
        print(f"[finance] posted trajectory usage task={task_name} "
              f"traj={payload['trajectory_id'][:8]} status={status}")
        return {"status": status, "body": body, "payload": payload}
    except Exception as exc:
        print(f"[finance] usage report failed for {task_name}: "
              f"{type(exc).__name__}: {exc} -- run unaffected", file=sys.stderr)
        return None
