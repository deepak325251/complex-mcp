from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FailureClass(str, Enum):
    REFUSED = "refused"
    NO_TOOL_CALLS = "no_tool_calls"
    FORMAT_ERROR = "format_error"
    WRONG_TOOL = "wrong_tool"
    MISSING_PREREQ = "missing_prereq"
    DIRTY_STATE_IGNORED = "dirty_state_ignored"
    DISTRACTION_DERAILED = "distraction_derailed"
    HALLUCINATED_ARG = "hallucinated_arg"
    PARTIAL_COMPLETION = "partial_completion"
    TOOL_ERROR_UNRECOVERED = "tool_error_unrecovered"
    MAX_TURNS_EXCEEDED = "max_turns_exceeded"
    UNKNOWN = "unknown"
    EXECUTION_DROP = "execution_drop"
    ERR_RECOVERY = "err_recovery"
    TASK_MISUNDERSTANDING = "task_misunderstanding"
    FAULTY_SYNTHESIS = "faulty_synthesis"
    RESPONSE_MISPARSING = "response_misparsing"
    EARLY_TERMINATION = "early_termination"
    HALLUCINATED_FACT = "hallucinated_fact"
    LOGICAL_ERROR = "logical_error"
    CONSTRAINT_VIOLATION = "constraint_violation"
    CLEAN_SLATE_BIAS = "clean_slate_bias"
    REFERENTIAL_ERROR = "referential_error"
    OVER_ACTION = "over_action"
    ANALYSIS_ERROR = "analysis_error"
    INFRA_ERROR = "infra_error"
    TIMEOUT = "timeout"
    SOLVED = "solved"


TOOL_CALL_MODES: dict[str, dict[str, str]] = {
    "format_error": {
        "description": "Right tool, wrong parameters: missing arguments, bad types, or wrong values (malformed_call).",
        "example": "Called place_market_order with quantity as a string when the schema wants int.",
    },
    "wrong_tool": {
        "description": "Picked a tool that cannot accomplish the subtask, though a correct one was available.",
        "example": "Used search_items when the task needed search_items_in_shop scoped to one shop.",
    },
    "distraction_derailed": {
        "description": "Called a similar-looking but incorrect tool when the correct one was available (distractor lever).",
        "example": "Called search_hotels when the task needed search_flights.",
    },
    "no_tool_calls": {
        "description": "Produced empty/trivial output with no tool call attempts.",
        "example": "Wrote a single sentence, never invoked a tool.",
    },
    "refused": {
        "description": "Declined to act — produced substantive text output but no tool calls (a no_tool_use variant).",
        "example": "Explained at length why the request could not be completed instead of trying.",
    },
    "err_recovery": {
        "description": "A tool returned an error and the model could not adapt: retried identically, looped, or gave up.",
        "example": "Retried like_moment five times on a transient error instead of calling acc_network.",
    },
    "tool_error_unrecovered": {
        "description": "Hit multiple tool errors and did not recover (a heavier err_recovery variant).",
        "example": "Three consecutive backend errors, then gave up without alternative path.",
    },
}


COGNITIVE_MODES: dict[str, dict[str, str]] = {
    "task_misunderstanding": {
        "description": "Answered a different question than the one asked, or missed a key requirement.",
        "example": "Asked for top 4 stocks by market cap; bought top 4 by price.",
    },
    "faulty_synthesis": {
        "description": "Had the right tool outputs but combined or interpreted them incorrectly.",
        "example": "Retrieved four transaction values, summed instead of taking the top-ranked one.",
    },
    "response_misparsing": {
        "description": "Got valid tool output but misread its structure or extracted the wrong field.",
        "example": "Read 'price' from the item record when the task needed 'total_price' from the cart.",
    },
    "early_termination": {
        "description": "Understood the task but stopped before completing all required steps.",
        "example": "Bought the stocks and sent the messages, never booked the flight.",
    },
    "partial_completion": {
        "description": "Made real progress (some state matches GT) but did not finish (an early_termination variant).",
        "example": "Added items to cart, called wait_payment_password, then produced [END] without checkout_all.",
    },
    "hallucinated_fact": {
        "description": "Stated something in the final answer that appeared in no tool output.",
        "example": "Reported a confirmation number the environment never returned.",
    },
    "hallucinated_arg": {
        "description": "Called valid tools with fabricated arguments (IDs, names) that don't exist in the sandbox.",
        "example": "Passed item_id='sku-9999999' when no such item is in the catalog.",
    },
    "logical_error": {
        "description": "Multi-step reasoning chain was flawed even though the underlying data were correct.",
        "example": "Weather was sunny, task said sunny implies business class, booked economy.",
    },
    "constraint_violation": {
        "description": "Ignored an explicit condition or filter stated in the prompt.",
        "example": "Prompt said 'two separate messages, no additional text'; sent one combined message.",
    },
    "execution_drop": {
        "description": (
            "Agent verbalized a planned action in reasoning but never emitted the "
            "corresponding tool call. Distinct from partial_completion (which stops "
            "early) and over_action (which does extra) -- here the plan is complete "
            "but one step slips between planning text and execution."
        ),
        "example": "Reasoning listed 'mark A read, mark B read, unstar C'; tool trace only shows the B and C calls.",
    },
}


STATEFUL_MODES: dict[str, dict[str, str]] = {
    "clean_slate_bias": {
        "description": (
            "Assumed an empty/default world and acted without verifying existing state. "
            "The gold trajectory reads before its first write; the model does not."
        ),
        "example": "Cart already held 3 items from a prior session; agent added its own and checked out all.",
    },
    "dirty_state_ignored": {
        "description": "Task required cleanup of pre-existing state but the agent did not modify that state (clean_slate_bias variant with an explicit cleanup requirement).",
        "example": "Prior session left a card in cart; task said 'buy only apples'; agent added apples but did not remove the card.",
    },
    "missing_prereq": {
        "description": (
            "Hit a gate rejection and never called the tool that opens the gate, or "
            "abandoned the branch instead of satisfying the precondition (missing_prerequisite)."
        ),
        "example": "Got 'Please enter the trading password first' and never called wait_trade_password.",
    },
    "referential_error": {
        "description": (
            "Acted on the wrong entity because it failed to resolve identity against live state. "
            "Gold resolves identity first; the model assumed or took the first candidate."
        ),
        "example": "Task said 'my friend picks me up'; agent booked the ticket for a pre-existing passenger.",
    },
    "over_action": {
        "description": (
            "Reached the goal but damaged state that should not have changed (Rb > 0). "
            "Collateral damage, not incompletion."
        ),
        "example": "Bought the right stock but also liquidated an unrelated position while 'cleaning up'.",
    },
}


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


MODE_TO_CATEGORY: dict[str, str] = {
    **{m: "tool_call" for m in TOOL_CALL_MODES},
    **{m: "cognitive" for m in COGNITIVE_MODES},
    **{m: "stateful" for m in STATEFUL_MODES},
}


PROGRAMMATIC_LABELS: list[str] = [
    "analysis_error",
    "infra_error",
    "timeout",
    "solved",
    "max_turns_exceeded",
    "unknown",
]


DETERMINISTIC_MODES: set[str] = {
    "format_error",
    "no_tool_calls",
    "refused",
    "err_recovery",
    "tool_error_unrecovered",
    "early_termination",
    "partial_completion",
    "clean_slate_bias",
    "dirty_state_ignored",
    "missing_prereq",
    "referential_error",
    "over_action",
    "execution_drop",
}


LEVER_TO_EXPECTED_MODES: dict[str, set[str]] = {
    "dirty_state": {"clean_slate_bias", "dirty_state_ignored", "over_action", "execution_drop"},
    "transient_failure": {"err_recovery", "tool_error_unrecovered"},
    "hidden_prerequisite": {"missing_prereq"},
    "referential_ambiguity": {"referential_error"},
    "distractor_saturation": {"wrong_tool", "no_tool_calls", "distraction_derailed"},
    "long_chain": {"early_termination", "partial_completion", "faulty_synthesis", "hallucinated_fact"},
    "cross_server": {"response_misparsing", "faulty_synthesis"},
    "conditional_branch": {"logical_error", "constraint_violation"},
    "refusal": {"refused", "task_misunderstanding"},
}


FAILURE_DESCRIPTIONS: dict[FailureClass, str] = {
    FailureClass.REFUSED: TOOL_CALL_MODES["refused"]["description"],
    FailureClass.NO_TOOL_CALLS: TOOL_CALL_MODES["no_tool_calls"]["description"],
    FailureClass.FORMAT_ERROR: TOOL_CALL_MODES["format_error"]["description"],
    FailureClass.WRONG_TOOL: TOOL_CALL_MODES["wrong_tool"]["description"],
    FailureClass.DISTRACTION_DERAILED: TOOL_CALL_MODES["distraction_derailed"]["description"],
    FailureClass.ERR_RECOVERY: TOOL_CALL_MODES["err_recovery"]["description"],
    FailureClass.TOOL_ERROR_UNRECOVERED: TOOL_CALL_MODES["tool_error_unrecovered"]["description"],
    FailureClass.TASK_MISUNDERSTANDING: COGNITIVE_MODES["task_misunderstanding"]["description"],
    FailureClass.FAULTY_SYNTHESIS: COGNITIVE_MODES["faulty_synthesis"]["description"],
    FailureClass.RESPONSE_MISPARSING: COGNITIVE_MODES["response_misparsing"]["description"],
    FailureClass.EARLY_TERMINATION: COGNITIVE_MODES["early_termination"]["description"],
    FailureClass.PARTIAL_COMPLETION: COGNITIVE_MODES["partial_completion"]["description"],
    FailureClass.HALLUCINATED_FACT: COGNITIVE_MODES["hallucinated_fact"]["description"],
    FailureClass.HALLUCINATED_ARG: COGNITIVE_MODES["hallucinated_arg"]["description"],
    FailureClass.LOGICAL_ERROR: COGNITIVE_MODES["logical_error"]["description"],
    FailureClass.CONSTRAINT_VIOLATION: COGNITIVE_MODES["constraint_violation"]["description"],
    FailureClass.EXECUTION_DROP: COGNITIVE_MODES["execution_drop"]["description"],
    FailureClass.CLEAN_SLATE_BIAS: STATEFUL_MODES["clean_slate_bias"]["description"],
    FailureClass.DIRTY_STATE_IGNORED: STATEFUL_MODES["dirty_state_ignored"]["description"],
    FailureClass.MISSING_PREREQ: STATEFUL_MODES["missing_prereq"]["description"],
    FailureClass.REFERENTIAL_ERROR: STATEFUL_MODES["referential_error"]["description"],
    FailureClass.OVER_ACTION: STATEFUL_MODES["over_action"]["description"],
    FailureClass.MAX_TURNS_EXCEEDED: "Agent ran out of turns before reaching [END].",
    FailureClass.ANALYSIS_ERROR: "Trajectory could not be parsed or analysed.",
    FailureClass.INFRA_ERROR: "Harness or infrastructure error unrelated to model behavior.",
    FailureClass.TIMEOUT: "Agent exceeded wall-clock timeout.",
    FailureClass.SOLVED: "Task completed successfully; no failure to classify.",
    FailureClass.UNKNOWN: "No rule matched — inspect the transcript manually.",
}


@dataclass
class FailureVerdict:
    failure_class: FailureClass
    reason: str
    evidence: dict = field(default_factory=dict)
    category: str | None = None

    def __post_init__(self) -> None:
        if self.category is None:
            self.category = category_of(self.failure_class)

    def to_dict(self) -> dict:
        return {
            "failure_class": self.failure_class.value,
            "category": self.category,
            "reason": self.reason,
            "evidence": self.evidence,
        }


def category_of(mode: FailureClass | str) -> str:
    value = mode.value if isinstance(mode, FailureClass) else str(mode)
    if value in MODE_TO_CATEGORY:
        return MODE_TO_CATEGORY[value]
    if value in PROGRAMMATIC_LABELS:
        return "programmatic"
    return "unknown"


def get_taxonomy_prompt_text() -> str:
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
