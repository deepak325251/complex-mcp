"""mcp-stump -- hybrid MCP tool-calling harness for model-stumping tasks.

Sourcing, so the provenance stays legible:

  environment + traps + state-diff   ComplexMCP   (MIT, (c) 2025 AIDC-AI)
  equal function sets + DAG scoring  ETOM         (reimplemented from the paper)
  failure-taxonomy structure         MCP-Atlas    (MIT, (c) 2026 Scale)
  task/verifier shape, pass^k        MCPMark      (Apache-2.0)
  detailed -> fuzzy task generation  MCP-Bench    (reimplemented)
  task format, controls, ATIF, gates Harbor
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
