"""The VeriResearch graph.

    START -> planner -> researcher -> writer -> verifier -> [revise | finalize]
                                        ^                       |
                                        +-----------------------+

Why LangGraph rather than a single agent loop
---------------------------------------------
A while-loop agent with tools would be less code. It would also be strictly
worse here, for three reasons that are specific to this problem:

1. **The verifier must not be optional.** In a tool-calling loop the model
   decides whether to call `verify()`. It will skip it when it feels confident —
   which is exactly the case where verification matters most. As a graph edge,
   verification is structural: there is no path from writer to output that does
   not pass through the verifier. The guarantee moves from "the model usually
   remembers" to "the graph has no such edge".

2. **The baseline arm has to be the same system minus one node.** The headline
   metric compares "before the verifier existed" to "after". With an explicit
   graph that is a different compiled graph over identical node functions. With
   a single loop it would be a different prompt, and the comparison would be
   confounded by every other difference the prompt change introduced.

3. **Per-node cost, latency, and token attribution.** Langfuse traces map onto
   node boundaries. In a single loop everything is one span and you cannot tell
   whether your spend went to research or to verification — which is the first
   question anyone asks when the bill arrives.

The cost is real: more files, explicit state, reducers. That is the trade, and
for a system whose entire value proposition is "you can trust the output", the
structural guarantee is worth it.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from langgraph.graph import END, START, StateGraph

from .config import SETTINGS
from .nodes.planner import planner_node
from .nodes.researcher import researcher_node
from .nodes.verifier_node import (
    finalize_node,
    revise_node,
    should_revise,
    verifier_node,
)
from .nodes.writer import writer_node
from .state import RunState
from .tracing import traced_node

planner_node = traced_node("planner")(planner_node)
researcher_node = traced_node("researcher")(researcher_node)
writer_node = traced_node("writer")(writer_node)
verifier_node = traced_node("verifier")(verifier_node)
revise_node = traced_node("revise")(revise_node)
finalize_node = traced_node("finalize")(finalize_node)

Mode = Literal["full", "baseline"]


def build_graph(mode: Mode = "full", checkpointer: Any = None):
    """Compile the graph.

    `mode="baseline"` compiles planner -> researcher -> writer -> verifier ->
    finalize with the verifier in measure-only mode and no revision edge: the
    pre-verifier system, instrumented so it can be scored. `mode="full"` adds
    enforcement and the conditional revision loop.
    """
    graph = StateGraph(RunState)

    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("writer", writer_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "verifier")

    if mode == "baseline":
        # No revision edge and no enforcement — but the verifier still runs, so
        # the arm is measurable. See nodes/verifier_node.py.
        graph.add_edge("verifier", "finalize")
    else:
        graph.add_node("revise", revise_node)
        graph.add_conditional_edges(
            "verifier",
            should_revise,
            {"revise": "revise", "finalize": "finalize"},
        )
        graph.add_edge("revise", "writer")

    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def initial_state(topic: str, mode: Mode = "full", run_id: Optional[str] = None) -> RunState:
    return {
        "run_id": run_id or f"run_{uuid.uuid4().hex[:12]}",
        "topic": topic,
        "mode": mode,
        "sub_questions": [],
        "sources": {},
        "claims": {},
        "draft_markdown": "",
        "report": None,
        "revision_count": 0,
        "max_revisions": SETTINGS.graph.max_revisions,
        "revision_feedback": [],
        "verification_summary": {},
        "trace": [],
        "errors": [],
    }


def run(topic: str, mode: Mode = "full", **kwargs) -> RunState:
    """Convenience entrypoint: build, run, return final state."""
    compiled = build_graph(mode=mode)
    config = {"recursion_limit": 25}
    if kwargs.get("thread_id"):
        config["configurable"] = {"thread_id": kwargs["thread_id"]}
    return compiled.invoke(initial_state(topic, mode=mode), config=config)


def render_mermaid(mode: Mode = "full") -> str:
    """Mermaid source for the README diagram, generated from the real graph."""
    try:
        return build_graph(mode=mode).get_graph().draw_mermaid()
    except Exception:  # noqa: BLE001
        return ""
