"""Plan-shape scoring: dependency-aware precision/recall over a tool DAG.

Reimplemented from the ETOM paper (arXiv:2510.19423), which describes the
algorithm as "global relative order validation". The ETOM repo ships no LICENSE
file, so this is written from the published description rather than copied.

Why this exists alongside the state diff: a model can reach the right end state
by brute force (high Rc, low graph F1) or plan correctly and fail on execution
(high F1, low Rc). Those are different bugs. Neither ComplexMCP nor ETOM can
tell them apart on its own; running both is the point of the hybrid.

Ground truth is a list of steps, each step an *equal function set* -- any tool
in the set satisfies that step. Steps carry dependency indices. Getting this
wrong produces false negatives that punish correct behaviour and, because they
look like difficulty, corrupt the tier labels too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

ToolRef = tuple[str, str]  # (server, tool)


@dataclass
class GTNode:
    """One step in the gold plan."""

    index: int
    efs: set[ToolRef]                      # interchangeable tools for this step
    dependencies: set[int] = field(default_factory=set)
    optional: bool = False                 # e.g. a conditional branch not always taken

    @classmethod
    def from_dict(cls, index: int, step: Sequence[dict]) -> "GTNode":
        efs: set[ToolRef] = set()
        deps: set[int] = set()
        optional = False
        for alt in step:
            server = alt.get("server_name") or alt.get("server") or ""
            tool = alt.get("tool_name") or alt.get("tool") or ""
            efs.add((server, tool))
            deps.update(alt.get("dependencies", []) or [])
            optional = optional or bool(alt.get("optional"))
        return cls(index=index, efs=efs, dependencies=deps, optional=optional)


@dataclass
class GraphResult:
    precision: float
    recall: float
    f1: float
    exact_match: bool
    tp: int
    fp: int
    fn: int
    total_predictions: int
    total_gt_nodes: int
    matched_nodes: list[int] = field(default_factory=list)
    missing_nodes: list[int] = field(default_factory=list)
    misplaced: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "graph_f1": round(self.f1, 6),
            "graph_precision": round(self.precision, 6),
            "graph_recall": round(self.recall, 6),
            "graph_exact_match": self.exact_match,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "total_predictions": self.total_predictions,
            "total_gt_nodes": self.total_gt_nodes,
            "matched_nodes": self.matched_nodes,
            "missing_nodes": self.missing_nodes,
            "misplaced": self.misplaced,
        }


def parse_ground_truth(steps: Sequence[Sequence[dict]]) -> dict[int, GTNode]:
    return {i: GTNode.from_dict(i, s) for i, s in enumerate(steps) if s}


def evaluate(
    ground_truth: Sequence[Sequence[dict]],
    predicted: Sequence[ToolRef],
) -> GraphResult:
    """Score a predicted call sequence against the gold DAG.

    Both empty -> perfect (this is how a correct refusal scores).
    """
    gt = parse_ground_truth(ground_truth)

    if not gt and not predicted:
        return GraphResult(1.0, 1.0, 1.0, True, 0, 0, 0, 0, 0)
    if not gt:
        n = len(predicted)
        return GraphResult(0.0, 1.0, 0.0, False, 0, n, 0, n, 0)
    if not predicted:
        return GraphResult(0.0, 0.0, 0.0, False, 0, 0, len(gt), 0, len(gt),
                           missing_nodes=sorted(gt))

    # --- match each prediction to at most one unused GT node -----------------
    # One-time matching: repeating a tool must not score twice.
    pred_to_gt: dict[int, int] = {}
    used: set[int] = set()
    for pos, call in enumerate(predicted):
        for node_id, node in gt.items():
            if node_id not in used and call in node.efs:
                pred_to_gt[pos] = node_id
                used.add(node_id)
                break

    # First predicted position at which each GT node appears.
    gt_first_pos: dict[int, int] = {}
    for pos, node_id in pred_to_gt.items():
        gt_first_pos.setdefault(node_id, pos)

    # --- recall: did the plan cover the required nodes? ----------------------
    required = {i for i, n in gt.items() if not n.optional}
    covered = set(pred_to_gt.values())
    recall = len(covered & required) / len(required) if required else 1.0

    # --- precision: was each matched call correctly *placed*? ----------------
    correctly_placed = 0
    misplaced: list[dict] = []
    for pos, call in enumerate(predicted):
        node_id = pred_to_gt.get(pos)
        if node_id is None:
            continue
        ok, why = _deps_satisfied(node_id, pos, gt, gt_first_pos)
        if ok:
            correctly_placed += 1
        else:
            misplaced.append(
                {"position": pos, "tool": f"{call[0]}::{call[1]}",
                 "gt_node": node_id, "reason": why}
            )

    precision = correctly_placed / len(predicted) if predicted else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    tp = correctly_placed
    fp = len(predicted) - tp
    fn = len(required - covered)

    return GraphResult(
        precision=precision,
        recall=recall,
        f1=f1,
        exact_match=f1 == 1.0,
        tp=tp,
        fp=fp,
        fn=fn,
        total_predictions=len(predicted),
        total_gt_nodes=len(gt),
        matched_nodes=sorted(covered),
        missing_nodes=sorted(required - covered),
        misplaced=misplaced,
    )


def _deps_satisfied(
    node_id: int,
    pos: int,
    gt: dict[int, GTNode],
    gt_first_pos: dict[int, int],
) -> tuple[bool, str]:
    """A call is correctly placed iff every prerequisite appeared strictly earlier.

    Checking each node independently is what stops one misordering from
    cascading into total failure.
    """
    for dep in gt[node_id].dependencies:
        if dep not in gt_first_pos:
            return False, f"dependency step {dep} never called"
        if gt_first_pos[dep] >= pos:
            return False, f"dependency step {dep} called at or after this step"
    return True, ""


def flatten_trace(trace: Iterable[dict]) -> list[ToolRef]:
    """Environment trace -> ordered (server, tool) pairs.

    Only successful and env-rejected calls count as attempts; malformed calls
    that never reached a server are scored by the taxonomy, not the DAG.

    The facade records the *qualified* name ("LightShop::search_items") because
    that is what it dispatches on, while gold plans carry the bare tool name.
    Strip the prefix so the two sides compare.
    """
    out: list[ToolRef] = []
    for rec in trace:
        if rec.get("status") == "malformed":
            continue
        server = rec.get("server", "")
        tool = rec.get("tool", "")
        if "::" in tool:
            prefix, _, bare = tool.partition("::")
            server = server or prefix
            tool = bare
        out.append((server, tool))
    return out
