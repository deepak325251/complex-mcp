from typing import Dict, Any
import json

TOOL_START_SEQ = "<tool>"
TOOL_STOP_SEQ = "</tool>"

# Extended-thinking is carried in the flat `output` stream as an explicit,
# self-delimiting block so the trajectory writer can tell the model's REAL
# reasoning (from the backend's thinking channel) apart from its visible speech.
# The signature (proof the reasoning is model-generated) rides on the open tag.
THINK_STOP_SEQ = "</thinking>"


def thinking_block(text: str, signatures=None) -> str:
    """Render captured extended-thinking as a `<thinking signature="...">` block.

    Only call this when `text` is real reasoning surfaced by the backend -- never
    for visible assistant text. `signatures` is the per-turn signature list; it is
    folded onto the open tag so parse_trajectory can re-associate it with the step
    without a fragile parallel index.
    """
    sig = ",".join(s for s in (signatures or []) if s)
    open_tag = f'<thinking signature="{sig}">' if sig else "<thinking>"
    return f"{open_tag}\n{text}\n{THINK_STOP_SEQ}"

def parse_tool(msg: str) -> Dict[str, Any] | None:
    msg = msg.strip()
    start = msg.rfind(TOOL_START_SEQ)
    if start == -1:
        return None
    tool_calling_msg = msg[start + len(TOOL_START_SEQ) :].removesuffix(TOOL_STOP_SEQ).strip()
    tool_calling_req = None
    try:
        tool_calling_req = json.loads(tool_calling_msg)
    except Exception as e:
        return None
    
    return tool_calling_req

