"""An empty assistant turn must never enter the message history.

Anthropic rejects a request whose history contains a whitespace-only text block
("messages: text content blocks must contain non-whitespace text"). The offending
turn is accepted fine; the NEXT call 400s, so a run dies mid-rollout with an error
that points at the wrong turn. Observed live: a pass@2 aborted after 29 tool calls.

A turn that spends its whole budget on extended thinking arrives with content
None or "" -- realistic, and likelier since thinking is on by default.
"""

import re
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "client" / "agent.py").read_text()


def test_none_content_is_normalised():
    assert "resp.choices[0].message.content or \"\"" in SRC


def test_empty_assistant_turn_is_not_appended():
    """The append must be guarded, not unconditional."""
    m = re.search(
        r'if msg and msg\.strip\(\):\s*\n\s*messages\.append\(\{\s*\n'
        r'\s*"role": "assistant",\s*\n\s*"content": msg',
        SRC)
    assert m, "assistant append is not guarded against empty content"


def test_unguarded_append_is_gone():
    """Guard against a future edit reintroducing the unconditional append."""
    unguarded = re.search(
        r'\n                output\.append\(msg\)\n'
        r'                messages\.append\(', SRC)
    assert unguarded is None


def test_episode_still_terminates_when_model_emits_nothing():
    """Skipping the turn must not remove the escape hatch."""
    assert "cnt_without_tc >= 5" in SRC
