"""ATIF (Agent Trajectory Interchange Format) helpers.

Harbor writes `agent/trajectory.json` in ATIF for every trial. That is the
delivery format for trajectories -- it is already designed for SFT and RL
consumption, so we read and enrich it rather than inventing a schema.

Fields that carry the weight for stump data:
  reasoning_content       the model's own account of why it did the wrong thing
  agent.tool_definitions  the exact tool set presented (records the distractor
                          count at that knob setting)
  tool_calls/observation  gate rejections and injected errors appear verbatim
                          in observation.results[].content
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "ATIF-v1.7"


@dataclass
class Trajectory:
    raw: dict

    @classmethod
    def load(cls, path: str | Path) -> "Trajectory":
        return cls(json.loads(Path(path).read_text()))

    @property
    def schema_version(self) -> str:
        return self.raw.get("schema_version", "")

    @property
    def steps(self) -> list[dict]:
        return self.raw.get("steps", [])

    @property
    def final_metrics(self) -> dict:
        return self.raw.get("final_metrics", {}) or {}

    def tool_calls(self) -> list[dict]:
        """Flatten every tool call in order, pairing each with its observation."""
        out: list[dict] = []
        for step in self.steps:
            if step.get("source") != "agent":
                continue
            observations = {
                r.get("source_call_id"): r.get("content")
                for r in (step.get("observation") or {}).get("results", [])
            }
            for call in step.get("tool_calls") or []:
                out.append(
                    {
                        "step_id": step.get("step_id"),
                        "tool_call_id": call.get("tool_call_id"),
                        "function_name": call.get("function_name"),
                        "arguments": call.get("arguments"),
                        "observation": observations.get(call.get("tool_call_id")),
                        "reasoning": step.get("reasoning_content"),
                    }
                )
        return out

    def reasoning(self) -> list[str]:
        return [
            s["reasoning_content"]
            for s in self.steps
            if s.get("source") == "agent" and s.get("reasoning_content")
        ]

    def final_message(self) -> str:
        for step in reversed(self.steps):
            if step.get("source") == "agent" and not step.get("tool_calls"):
                msg = step.get("message")
                return msg if isinstance(msg, str) else json.dumps(msg)
        return ""

    def enrich(self, *, env_trace: list[dict], diagnosis: dict, judge: dict) -> dict:
        """Attach harness findings to ATIF `extra` without breaking the schema."""
        out = dict(self.raw)
        extra = dict(out.get("extra") or {})
        extra["mcp_stump"] = {
            "environment_trace": env_trace,
            "diagnosis": diagnosis,
            "judge": judge,
        }
        out["extra"] = extra
        return out

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.raw, indent=2))
        return p


# --------------------------------------------------------------------------
# Paired export -- the training artifact
# --------------------------------------------------------------------------

def build_pair(
    *,
    task_name: str,
    seed: int,
    instruction: str,
    failed: Trajectory,
    gold: Trajectory | None,
    diagnosis: dict,
    judge: dict,
    env_trace: list[dict],
    levers: list[str],
) -> dict:
    """One failed rollout paired with the gold rollout.

    This is the shape a client trains on: a negative with a labelled reason,
    and the positive it should have produced. A reward of 0 with no reason is
    much weaker supervision.
    """
    return {
        "task": task_name,
        "seed": seed,
        "levers": levers,
        "instruction": instruction,
        "failure": {
            "mode": diagnosis.get("primary_failure", {}).get("mode"),
            "category": diagnosis.get("primary_failure", {}).get("category"),
            "explanation": diagnosis.get("primary_failure", {}).get("explanation"),
            "all_modes": diagnosis.get("all_modes", []),
            "evidence": diagnosis.get("evidence", []),
            "crux_aligned": diagnosis.get("crux_aligned"),
        },
        "scores": {
            "completion_rate": judge.get("completion_rate"),
            "misbehaving_rate": judge.get("misbehaving_rate"),
            "passed": judge.get("passed"),
        },
        "rejected": {
            "trajectory": failed.raw,
            "tool_calls": failed.tool_calls(),
            "reasoning": failed.reasoning(),
            "final_message": failed.final_message(),
        },
        "chosen": (
            {
                "trajectory": gold.raw,
                "tool_calls": gold.tool_calls(),
                "final_message": gold.final_message(),
            }
            if gold
            else None
        ),
        "environment_trace": env_trace,
    }


def write_pairs(pairs: Iterable[dict], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as fh:
        for pair in pairs:
            fh.write(json.dumps(pair, default=str) + "\n")
    return p


def synth_from_trace(trace: list[dict], *, agent: str, model: str) -> dict:
    """Build a minimal ATIF document from an environment trace alone.

    Used for the oracle, which executes a scripted solve.sh and therefore has
    no model trajectory of its own -- but we still want the gold side of a pair
    in the same schema as the rejected side.
    """
    steps: list[dict] = []
    for i, rec in enumerate(trace, start=1):
        steps.append(
            {
                "step_id": i,
                "timestamp": rec.get("ts"),
                "source": "agent",
                "message": "",
                "model_name": model,
                "tool_calls": [
                    {
                        "tool_call_id": f"oracle_{i}",
                        "function_name": rec.get("tool"),
                        "arguments": rec.get("args", {}),
                    }
                ],
                "observation": {
                    "results": [
                        {"source_call_id": f"oracle_{i}", "content": rec.get("response", "")}
                    ]
                },
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "trajectory_id": "oracle",
        "agent": {"name": agent, "version": "1.0.0", "model_name": model},
        "steps": steps,
        "final_metrics": {"total_steps": len(steps)},
    }


# --------------------------------------------------------------------------
# complex-mcp adapter (kept in sync with the reasoning/usage capture below)
# --------------------------------------------------------------------------

def from_complexmcp(traj: dict, *, agent: str = "complexmcp", model: str = "",
                    usage: dict | None = None, query: str = "") -> dict:
    """Convert complex-mcp's parse_trajectory() shape into an ATIF-v1.7 document.

    complex-mcp records one agent step per tool call with an inline `response`;
    ATIF wants agent steps carrying tool_calls plus an observation block keyed by
    tool_call_id. The trailing final_message becomes a final agent step with no
    tool_calls, which is what Trajectory.final_message() looks for.
    """
    steps: list[dict] = []
    # Opening user turn: the task prompt as steps[0] (source:"user"), for
    # symmetry with trajectory.messages.json turn 0 and so replay/analytics see
    # the instruction the agent acted on -- not just the agent's steps.
    if query:
        steps.append({
            "step_id": 0,
            "source": "user",
            "message": query,
        })
    for step in traj.get("steps", []):
        call_id = f"call_{step['step']}"
        response = step.get("response")
        content = response if isinstance(response, str) else json.dumps(response)
        # reasoning_content is the model's REAL extended thinking (None when the
        # backend surfaced none) -- NOT the visible speech, which rides in
        # `message`. reasoning_signatures are attached only when thinking is real,
        # so a signature never vouches for text that isn't there.
        atif_step = {
            "step_id": step["step"],
            "source": "agent",
            "reasoning_content": step.get("reasoning") or None,
            "message": step.get("message", ""),
            "model_name": model,
            "tool_calls": [
                {
                    "tool_call_id": call_id,
                    "function_name": step.get("tool"),
                    "arguments": step.get("arguments", {}),
                }
            ],
            "observation": {
                "results": [
                    {"source_call_id": call_id, "content": content}
                ]
            },
        }
        _sig = step.get("signature")
        if _sig:
            atif_step["reasoning_signatures"] = _sig if isinstance(_sig, list) else [_sig]
        steps.append(atif_step)
    steps.append(
        {
            "step_id": len(steps) + 1,
            "source": "agent",
            "message": traj.get("final_message", ""),
            "model_name": model,
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "trajectory_id": "complexmcp",
        "agent": {"name": agent, "version": "1.0.0", "model_name": model},
        "steps": steps,
        "final_metrics": {"total_steps": len(steps), "usage": usage or {}},
    }
