"""Failure taxonomy for stateful MCP tool-calling.

Structure and the first eleven modes follow MCP-Atlas
(services/diagnostics/mcp_failure_taxonomy.py, MIT, (c) 2026 Scale).

Four modes are added here. Atlas's taxonomy was built for read-mostly,
single-answer tasks; a stateful side-effecting sandbox produces failures it has
no name for. Those four are the ones our corpus is specifically built to
provoke, so they are the ones that matter most for stump labelling.

Every mode is *programmatically* detectable from the environment trace plus the
judge result -- see mcp_stump.classify. The LLM-judge schema is kept for
optional second-opinion labelling, not as the primary path.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Family 1 -- how the model interacted with tools
# --------------------------------------------------------------------------

TOOL_CALL_MODES: dict[str, dict[str, str]] = {
    "malformed_call": {
        "description": "Right tool, wrong parameters: missing arguments, bad types, or wrong values.",
        "example": "Called place_market_order with quantity as a string when the schema wants int.",
    },
    "wrong_tool": {
        "description": "Picked a tool that cannot accomplish the subtask, though a correct one was available.",
        "example": "Used search_items when the task needed search_items_in_shop scoped to one shop.",
    },
    "no_tool_use": {
        "description": "Answered from internal knowledge without calling any tool, though tools were required.",
        "example": "Claimed the cart was empty without calling get_cart_summary.",
    },
    "err_recovery": {
        "description": "A tool returned an error and the model could not adapt: retried identically, looped, or gave up.",
        "example": "Retried like_moment five times on a transient network error instead of calling acc_network.",
    },
}

# --------------------------------------------------------------------------
# Family 2 -- how the model reasoned about the task
# --------------------------------------------------------------------------

COGNITIVE_MODES: dict[str, dict[str, str]] = {
    "task_misunderstanding": {
        "description": "Answered a different question than the one asked, or missed a key requirement.",
        "example": "Asked for the top 4 stocks by market cap; bought the top 4 by price.",
    },
    "faulty_synthesis": {
        "description": "Had the right tool outputs but combined or interpreted them incorrectly.",
        "example": "Retrieved all four transaction values, then summed instead of taking the top-ranked one.",
    },
    "response_misparsing": {
        "description": "Got valid tool output but misread its structure or extracted the wrong field.",
        "example": "Read 'price' from the item record when the task needed 'total_price' from the cart.",
    },
    "early_termination": {
        "description": "Understood the task but stopped before completing all required steps.",
        "example": "Bought the stocks and sent the messages, never booked the flight.",
    },
    "hallucinated_fact": {
        "description": "Stated something in the final answer that appeared in no tool output.",
        "example": "Reported a confirmation number the environment never returned.",
    },
    "logical_error": {
        "description": "Multi-step reasoning chain was flawed even though the underlying data were correct.",
        "example": "Weather was sunny, task said sunny implies business class, booked economy.",
    },
    "constraint_violation": {
        "description": "Ignored an explicit condition or filter stated in the prompt.",
        "example": "Prompt said 'two separate messages, without any additional text'; sent one combined message.",
    },
}

# --------------------------------------------------------------------------
# Family 3 -- stateful-environment failures (added here; no Atlas analogue)
#
# These are the modes the sandbox is engineered to provoke. They are what a
# read-only benchmark structurally cannot observe.
# --------------------------------------------------------------------------

STATEFUL_MODES: dict[str, dict[str, str]] = {
    "clean_slate_bias": {
        "description": (
            "Assumed an empty/default world and acted without verifying existing state. "
            "The gold trajectory reads before its first write; the model does not."
        ),
        "example": "Cart already held 3 items from a prior session; agent added its own and checked out all of them.",
    },
    "missing_prerequisite": {
        "description": (
            "Hit a gate rejection and never called the tool that opens the gate, or "
            "abandoned the branch instead of satisfying the precondition."
        ),
        "example": "Got 'Please enter the trading password first' and never called wait_trade_password.",
    },
    "referential_error": {
        "description": (
            "Acted on the wrong entity because it failed to resolve identity against live state. "
            "Gold resolves identity first; the model assumed or took the first candidate."
        ),
        "example": "Task said 'my friend picks me up'; agent booked the ticket for a pre-existing passenger record.",
    },
    "over_action": {
        "description": (
            "Reached the goal but damaged state that should not have changed (Rb > 0). "
            "Collateral damage, not incompletion."
        ),
        "example": "Bought the right stock but also liquidated an unrelated position while 'cleaning up'.",
    },
}

# --------------------------------------------------------------------------
# Derived constants
# --------------------------------------------------------------------------

FAILURE_TAXONOMY: dict[str, dict[str, dict[str, str]]] = {
    "tool_call": TOOL_CALL_MODES,
    "cognitive": COGNITIVE_MODES,
    "stateful": STATEFUL_MODES,
}

ALL_MODES: list[str] = [
    *TOOL_CALL_MODES,
    *COGNITIVE_MODES,
    *STATEFUL_MODES,
]

# Mode -> family. Authoritative: category_split is derived from the primary
# mode, ignoring any category an LLM judge might fill in. Defensive against
# judge drift (pattern borrowed from Atlas).
MODE_TO_CATEGORY: dict[str, str] = {
    **{m: "tool_call" for m in TOOL_CALL_MODES},
    **{m: "cognitive" for m in COGNITIVE_MODES},
    **{m: "stateful" for m in STATEFUL_MODES},
}

# Labels assigned without any judgement (unparseable trajectory, infra error).
PROGRAMMATIC_LABELS: list[str] = [
    "analysis_error",
    "infra_error",
    "timeout",
    "solved",
]

# Modes the harness detects deterministically from trace + judge output.
# Anything outside this set needs an LLM second opinion or human review.
DETERMINISTIC_MODES: set[str] = {
    "malformed_call",
    "no_tool_use",
    "err_recovery",
    "early_termination",
    "clean_slate_bias",
    "missing_prerequisite",
    "referential_error",
    "over_action",
}

# Which stump levers are *designed* to produce which mode. Used by the
# difficulty_crux check: if a task advertises a lever but the model failed for
# an unrelated reason, the task has unintended difficulty.
LEVER_TO_EXPECTED_MODES: dict[str, set[str]] = {
    "dirty_state": {"clean_slate_bias", "over_action"},
    "transient_failure": {"err_recovery"},
    "hidden_prerequisite": {"missing_prerequisite"},
    "referential_ambiguity": {"referential_error"},
    "distractor_saturation": {"wrong_tool", "no_tool_use"},
    # hallucinated_fact belongs here: the characteristic long-chain failure is
    # completing a correct prefix, skipping the final commit, and reporting the
    # whole thing as done.
    "long_chain": {"early_termination", "faulty_synthesis", "hallucinated_fact"},
    "cross_server": {"response_misparsing", "faulty_synthesis"},
    "conditional_branch": {"logical_error", "constraint_violation"},
    "refusal": {"task_misunderstanding"},
}


def get_taxonomy_prompt_text() -> str:
    """Failure-mode definitions for an LLM judge prompt."""
    families = [
        ("TOOL CALL FAMILY -- how the model interacted with tools", TOOL_CALL_MODES),
        ("COGNITIVE FAMILY -- how the model reasoned about the task", COGNITIVE_MODES),
        ("STATEFUL FAMILY -- how the model handled a live, non-empty environment", STATEFUL_MODES),
    ]
    lines: list[str] = []
    for header, modes in families:
        lines.append(f"{header}:")
        for mode, info in modes.items():
            lines.append(f"- {mode}: {info['description']} (e.g., {info['example']})")
        lines.append("")
    return "\n".join(lines).rstrip()


def get_diagnosis_schema() -> dict:
    """JSON schema for structured diagnosis output."""
    failure_entry = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ALL_MODES},
            "category": {"type": "string", "enum": ["tool_call", "cognitive", "stateful"]},
            "is_root_cause": {"type": "boolean"},
            "explanation": {"type": "string"},
            "evidence_step_ids": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["mode", "category", "is_root_cause", "explanation"],
    }
    return {
        "type": "object",
        "properties": {
            "primary_failure": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ALL_MODES},
                    "category": {"type": "string", "enum": ["tool_call", "cognitive", "stateful"]},
                    "explanation": {"type": "string"},
                },
                "required": ["mode", "category", "explanation"],
            },
            "all_failures": {"type": "array", "items": failure_entry},
            "confidence": {"type": "number"},
            "summary": {"type": "string"},
        },
        "required": ["primary_failure", "all_failures", "confidence", "summary"],
    }


def category_of(mode: str) -> str:
    """Authoritative family lookup."""
    return MODE_TO_CATEGORY.get(mode, "unknown")
