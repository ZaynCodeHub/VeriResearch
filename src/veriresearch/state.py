"""Core data model for VeriResearch.

Design note (the auditability requirement):
    A `Claim` never stores source *text* directly. It stores `evidence` — a list of
    `EvidenceSpan` objects, each of which points at a `Source` by id AND carries the
    exact character offsets of the span that was shown to the judge. The full raw
    text of every source lives in `RunState.sources` and is never discarded.

    That means for any claim in the final report you can reconstruct, exactly:
      - which source documents were consulted,
      - which span of each document the judge actually read,
      - what the judge said about it and how confident it was.

    This is what makes "click a claim, see the text it was checked against" a
    lookup rather than a re-derivation.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# --------------------------------------------------------------------------- #
# Verification vocabulary
# --------------------------------------------------------------------------- #


class VerificationLabel(str, Enum):
    """The four-way verdict a judge returns for a (claim, evidence) pair.

    Deliberately four-way rather than binary: the difference between "the source
    is silent on this" (UNSUPPORTED) and "the source says the opposite"
    (CONTRADICTED) is the single most useful signal in a research report, and a
    binary faithful/unfaithful metric throws it away.
    """

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"

    @property
    def is_publishable(self) -> bool:
        """Whether the Writer may keep this claim in the final report."""
        return self in (VerificationLabel.SUPPORTED, VerificationLabel.PARTIALLY_SUPPORTED)

    @property
    def ui_color(self) -> str:
        """Colour band for the React frontend."""
        return {
            VerificationLabel.SUPPORTED: "green",
            VerificationLabel.PARTIALLY_SUPPORTED: "yellow",
            VerificationLabel.UNSUPPORTED: "red",
            VerificationLabel.CONTRADICTED: "red",
        }[self]


# --------------------------------------------------------------------------- #
# Sources and evidence
# --------------------------------------------------------------------------- #


class Source(BaseModel):
    """A retrieved document. `raw_text` is retained verbatim, forever."""

    id: str = Field(default_factory=lambda: _new_id("src"))
    url: str
    title: str = ""
    raw_text: str
    snippet: str = ""
    search_query: str = ""
    retrieved_by: str = ""          # which sub-question pulled this in
    fetched_at: str = Field(default_factory=_now)
    content_hash: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()[:16]

    def span(self, start: int, end: int) -> str:
        return self.raw_text[start:end]


class EvidenceSpan(BaseModel):
    """A pointer into a Source, plus the resolved text for convenience.

    `char_start`/`char_end` are the contract. `text` is a cached slice and is
    asserted to match on load — if it ever drifts, the audit trail is broken and
    we want to know loudly.
    """

    source_id: str
    char_start: int
    char_end: int
    text: str
    locator: str = ""               # human-readable, e.g. "para 3, sent 2"

    def verify_against(self, source: Source) -> bool:
        return source.raw_text[self.char_start : self.char_end] == self.text


# --------------------------------------------------------------------------- #
# Claims and judgments
# --------------------------------------------------------------------------- #


class Judgment(BaseModel):
    """One judge's verdict on one (claim, evidence-span) pair.

    `quoted_span` is the text the judge says justifies its verdict. `grounded`
    records whether that quote was actually found verbatim in the source. An
    ungrounded quote means the judge hallucinated its own justification, which is
    a strong signal to distrust the verdict — see verify/grounding.py.
    """

    claim_id: str
    source_id: str
    label: VerificationLabel
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
    quoted_span: str = ""
    grounded: bool = True
    backend: str = "unknown"        # "llm:grok-4" | "nli:deberta" | "heuristic"
    samples: int = 1                # self-consistency sample count
    agreement: float = 1.0          # fraction of samples agreeing with `label`
    latency_ms: float = 0.0
    raw_response: Optional[str] = None


class ClaimVerification(BaseModel):
    """Aggregated verdict for a claim across all of its evidence."""

    claim_id: str
    label: VerificationLabel
    confidence: float = Field(ge=0.0, le=1.0)
    judgments: list[Judgment] = Field(default_factory=list)
    decisive_source_id: Optional[str] = None
    aggregation_rule: str = ""

    @property
    def is_publishable(self) -> bool:
        return self.label.is_publishable


class Claim(BaseModel):
    """An atomic, independently checkable assertion extracted from the draft."""

    id: str = Field(default_factory=lambda: _new_id("clm"))
    text: str
    section: str = ""
    order: int = 0
    sub_question_id: Optional[str] = None
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    verification: Optional[ClaimVerification] = None
    revision_of: Optional[str] = None   # set when the reviser rewrites a weak claim

    @property
    def source_ids(self) -> list[str]:
        seen, out = set(), []
        for e in self.evidence:
            if e.source_id not in seen:
                seen.add(e.source_id)
                out.append(e.source_id)
        return out


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #


class SubQuestion(BaseModel):
    id: str = Field(default_factory=lambda: _new_id("sq"))
    text: str
    rationale: str = ""
    search_queries: list[str] = Field(default_factory=list)
    status: Literal["pending", "researched", "failed"] = "pending"


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


class ReportSection(BaseModel):
    heading: str
    claim_ids: list[str] = Field(default_factory=list)
    prose: str = ""


class Report(BaseModel):
    topic: str
    title: str = ""
    sections: list[ReportSection] = Field(default_factory=list)
    markdown: str = ""
    dropped_claim_ids: list[str] = Field(default_factory=list)
    flagged_claim_ids: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# LangGraph state
# --------------------------------------------------------------------------- #


class Replace(dict):
    """Wrapper telling a merging reducer to overwrite instead of merge.

    The Writer produces a fresh claim set on every revision pass. Merging would
    leave the previous pass's claims in state, which would then be re-counted in
    the supported-rate — quietly corrupting the headline metric. Wrapping the
    return value in `Replace` makes that intent explicit and type-checkable
    rather than a magic string key.
    """


def _merge_dict(left: dict, right: dict) -> dict:
    if isinstance(right, Replace):
        return dict(right)
    out = dict(left)
    out.update(right)
    return out


def _extend(left: list, right: list) -> list:
    return [*left, *right]


class RunState(TypedDict, total=False):
    """The state object threaded through the LangGraph.

    Reducers matter here: `sources` and `claims` are keyed dicts merged by the
    reducer so that fan-out researcher branches can write concurrently without
    clobbering each other.
    """

    run_id: str
    topic: str
    mode: str                       # "full" | "baseline" — see graph.py

    sub_questions: list[SubQuestion]
    sources: Annotated[dict[str, Source], _merge_dict]
    claims: Annotated[dict[str, Claim], _merge_dict]

    draft_markdown: str
    report: Optional[Report]

    revision_count: int
    max_revisions: int
    revision_feedback: list[dict[str, Any]]
    verification_summary: dict[str, Any]
    trace: Annotated[list[dict[str, Any]], _extend]
    errors: Annotated[list[str], _extend]
