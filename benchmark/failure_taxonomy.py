from __future__ import annotations

from dataclasses import dataclass
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


FAILURE_DESCRIPTIONS: dict[FailureClass, str] = {
    FailureClass.REFUSED: "Agent declined to act — produced text output but no tool calls of any kind.",
    FailureClass.NO_TOOL_CALLS: "Agent produced empty or trivial output with no tool call attempts.",
    FailureClass.FORMAT_ERROR: "Agent attempted tool calls but every attempt was malformed (unparseable JSON, unknown tool names, etc.).",
    FailureClass.WRONG_TOOL: "Agent invoked tools outside the expected tool set for this task, indicating misidentification of the correct API.",
    FailureClass.MISSING_PREREQ: "Agent skipped a required setup call (e.g. wait_payment_password before checkout_all).",
    FailureClass.DIRTY_STATE_IGNORED: "Task required cleanup of pre-existing state but the agent did not modify that state.",
    FailureClass.DISTRACTION_DERAILED: "Agent used similar-looking but incorrect tools when the correct ones were available.",
    FailureClass.HALLUCINATED_ARG: "Agent called valid tools with fabricated arguments (IDs, names) that don't exist in the sandbox.",
    FailureClass.PARTIAL_COMPLETION: "Agent made real progress (some state changes match GT) but did not finish.",
    FailureClass.TOOL_ERROR_UNRECOVERED: "Agent hit multiple tool errors and did not recover.",
    FailureClass.MAX_TURNS_EXCEEDED: "Agent ran out of turns before reaching [END].",
    FailureClass.UNKNOWN: "No rule matched — inspect the transcript manually.",
}


@dataclass
class FailureVerdict:
    failure_class: FailureClass
    reason: str
    evidence: dict

    def to_dict(self) -> dict:
        return {
            "failure_class": self.failure_class.value,
            "reason": self.reason,
            "evidence": self.evidence,
        }
