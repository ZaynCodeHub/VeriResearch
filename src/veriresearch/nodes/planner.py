"""Planner node: topic -> 3-6 sub-questions.

Deterministic by default (six fixed angles, always in-range) so the graph is
runnable with no API key. When `GROK_API_KEY` is set, an LLM drafts
sharper, topic-specific sub-questions instead — parsed the same defensively as
`judges/llm_judge.py`, falling back to the deterministic set on any parse
failure rather than letting a malformed response break the run.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from ..config import SETTINGS
from ..state import RunState, SubQuestion

_ANGLES = [
    "What is {topic}, and what are its defining characteristics?",
    "What key facts, figures, or data define the current state of {topic}?",
    "What are the most significant recent developments related to {topic}?",
    "What are the main criticisms, risks, or open debates around {topic}?",
    "Who are the key organizations or people involved in {topic}, and what are their positions?",
    "What is the likely future trajectory or outlook for {topic}?",
]

_JSON_BLOCK = re.compile(r"\[.*\]", re.DOTALL)


def _deterministic_plan(topic: str) -> list[SubQuestion]:
    return [SubQuestion(text=angle.format(topic=topic), rationale="deterministic template") for angle in _ANGLES]


def _llm_plan(topic: str) -> Optional[list[SubQuestion]]:
    from ..llm import GrokClient

    system = (
        "You break a research topic into 3-6 specific, non-overlapping sub-questions that "
        "together give a well-rounded understanding of it. Respond with ONLY a JSON array, "
        'no markdown fences: [{"question": "...", "rationale": "...", '
        '"search_queries": ["...", "..."]}, ...]'
    )
    try:
        client = GrokClient(model=SETTINGS.verifier.llm_model)
        response = client.complete(system, f"Topic: {topic}", max_tokens=800)
    except Exception:
        return None

    match = _JSON_BLOCK.search(response.text)
    if not match:
        return None
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    sub_questions = []
    for item in items[: SETTINGS.graph.max_sub_questions]:
        question = str(item.get("question", "")).strip()
        if not question:
            continue
        sub_questions.append(
            SubQuestion(
                text=question,
                rationale=str(item.get("rationale", "")),
                search_queries=[str(q) for q in item.get("search_queries", []) if q],
            )
        )
    if len(sub_questions) < SETTINGS.graph.min_sub_questions:
        return None
    return sub_questions


def planner_node(state: RunState) -> dict[str, Any]:
    t0 = time.perf_counter()
    topic = state["topic"]

    sub_questions = _llm_plan(topic) if SETTINGS.planner.has_llm else None
    source = "llm"
    if sub_questions is None:
        sub_questions = _deterministic_plan(topic)
        source = "deterministic"

    return {
        "sub_questions": sub_questions,
        "trace": [
            {
                "node": "planner",
                "source": source,
                "sub_question_count": len(sub_questions),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        ],
    }
