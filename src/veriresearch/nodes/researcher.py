"""Researcher node: sub-question -> Source objects with raw text retained.

Tavily is used when `TAVILY_API_KEY` is set (optional `tavily-python` import,
so the package isn't a hard dependency). Without a key — or if a search call
fails — each sub-question gets one explicitly-labeled offline placeholder
source instead of silently producing nothing. The placeholder contains no
factual claims by design: anything the writer drafts from it correctly comes
back UNSUPPORTED, which is honest, versus inventing plausible-looking content
that would corrupt the headline metric.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..config import SETTINGS
from ..state import RunState, Source, SubQuestion
from .local_corpus import match_corpus


def _tavily_search(sq: SubQuestion) -> list[Source]:
    from tavily import TavilyClient

    client = TavilyClient(api_key=SETTINGS.research.tavily_api_key)
    queries = sq.search_queries or [sq.text]
    sources: list[Source] = []

    for query in queries[:2]:
        try:
            result = client.search(
                query,
                max_results=SETTINGS.research.max_results_per_query,
                include_raw_content=True,
            )
        except Exception:
            continue

        for item in result.get("results", []):
            raw_text = (item.get("raw_content") or item.get("content") or "").strip()
            if not raw_text:
                continue
            sources.append(
                Source(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    raw_text=raw_text,
                    snippet=(item.get("content") or "")[:280],
                    search_query=query,
                    retrieved_by=sq.id,
                )
            )

    return sources


def _offline_placeholder(sq: SubQuestion) -> list[Source]:
    return [
        Source(
            url="offline://no-search-backend",
            title="Offline placeholder (no TAVILY_API_KEY configured)",
            raw_text=(
                "No live search backend is configured for this run (set TAVILY_API_KEY to "
                f'enable real web search). This placeholder stands in for research on: '
                f'"{sq.text}". It intentionally contains no factual claims, so any sentence '
                "the writer drafts from it is correctly verified UNSUPPORTED rather than "
                "shipping invented content behind a false green checkmark."
            ),
            snippet="offline placeholder — no search backend configured",
            search_query=sq.text,
            retrieved_by=sq.id,
        )
    ]


def _offline_source_for(sq: SubQuestion, corpus_entry: Optional[Source]) -> list[Source]:
    """The bundled local corpus if the topic matched one, else the honest placeholder.

    See `local_corpus.py`: the corpus is a small, hand-vetted set of demo topics so
    the fully-offline path has real, checkable text to run the verifier against;
    everything outside that corpus stays an explicit no-content placeholder rather
    than inventing facts.
    """
    if corpus_entry is None:
        return _offline_placeholder(sq)
    return [
        corpus_entry.model_copy(
            update={
                "id": f"{corpus_entry.id}__{sq.id}",
                "search_query": sq.text,
                "retrieved_by": sq.id,
            }
        )
    ]


def researcher_node(state: RunState) -> dict[str, Any]:
    t0 = time.perf_counter()
    topic = state.get("topic", "")
    sub_questions = state.get("sub_questions", [])
    live = SETTINGS.research.has_live_search
    corpus_entry = None if live else match_corpus(topic)

    new_sources: dict[str, Source] = {}
    updated_sub_questions: list[SubQuestion] = []

    for sq in sub_questions:
        found: list[Source] = []
        if live:
            try:
                found = _tavily_search(sq)
            except Exception:
                found = []
        if not found:
            found = _offline_source_for(sq, corpus_entry)

        for source in found:
            new_sources[source.id] = source
        sq.status = "researched" if found else "failed"
        updated_sub_questions.append(sq)

    return {
        "sources": new_sources,
        "sub_questions": updated_sub_questions,
        "trace": [
            {
                "node": "researcher",
                "backend": "tavily" if live else "offline",
                "sources_found": len(new_sources),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        ],
    }
