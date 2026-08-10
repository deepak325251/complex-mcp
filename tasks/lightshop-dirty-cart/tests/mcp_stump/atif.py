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
