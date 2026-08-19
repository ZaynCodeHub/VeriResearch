"""All tunable thresholds and backend selection, in one place.

Every number here is a claim about how much to trust a judge, and every one of
them is arguable — so they live in one file, read from the environment, instead
of being scattered as magic numbers through the verifier. Change the system's
behaviour by changing this file or the corresponding env var, not by hunting
through judges/ and verify/ for a hardcoded 0.7.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


class VerifierConfig(BaseModel):
    """Thresholds the aggregation policy in verify/verifier.py reads.

    Threshold ordering matters more than the exact values: contradiction is
    checked first and has the lowest bar to clear (0.55) precisely because a
    false CONTRADICTED is cheap to recover from — a human re-reads one claim —
    while a false SUPPORTED ships silently. See verify/verifier.py's module
    docstring for the aggregation policy this feeds.
    """

    backend: str = Field(default_factory=lambda: os.getenv("VERIFIER_BACKEND", "auto"))
    evidence_window_chars: int = Field(default_factory=lambda: _env_int("VERIFIER_WINDOW_CHARS", 1200))

    support_threshold: float = Field(default_factory=lambda: _env_float("VERIFIER_SUPPORT_THRESHOLD", 0.70))
    partial_threshold: float = Field(default_factory=lambda: _env_float("VERIFIER_PARTIAL_THRESHOLD", 0.40))
    contradiction_threshold: float = Field(default_factory=lambda: _env_float("VERIFIER_CONTRADICTION_THRESHOLD", 0.55))

    # A judge that asserts SUPPORTED/CONTRADICTED without a quote that grounds,
    # or with a fabricated quote, gets its confidence multiplied by this. Low
    # enough that a fabricated SUPPORTED cannot survive the support_threshold.
    ungrounded_penalty: float = Field(default_factory=lambda: _env_float("VERIFIER_UNGROUNDED_PENALTY", 0.35))

    llm_model: str = Field(default_factory=lambda: os.getenv("VERIFIER_LLM_MODEL", "grok-4"))
    llm_samples: int = Field(default_factory=lambda: _env_int("VERIFIER_LLM_SAMPLES", 1))


class GraphConfig(BaseModel):
    max_revisions: int = Field(default_factory=lambda: _env_int("GRAPH_MAX_REVISIONS", 2))
    min_sub_questions: int = 3
    max_sub_questions: int = 6


class ResearchConfig(BaseModel):
    tavily_api_key: str = Field(default_factory=lambda: os.getenv("TAVILY_API_KEY", ""))
    max_results_per_query: int = Field(default_factory=lambda: _env_int("RESEARCH_MAX_RESULTS", 4))

    @property
    def has_live_search(self) -> bool:
        return bool(self.tavily_api_key)


class PlannerConfig(BaseModel):
    grok_api_key: str = Field(default_factory=lambda: os.getenv("GROK_API_KEY", ""))

    @property
    def has_llm(self) -> bool:
        return bool(self.grok_api_key)


class Settings(BaseModel):
    verifier: VerifierConfig = Field(default_factory=VerifierConfig)
    graph: GraphConfig = Field(default_factory=GraphConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)


SETTINGS = Settings()
