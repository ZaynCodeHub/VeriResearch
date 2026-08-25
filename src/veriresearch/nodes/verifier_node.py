"""Verifier, revise, and finalize nodes — the enforcement side of the graph.

`verifier_node` runs unconditionally in both `mode="baseline"` and
`mode="full"` graphs (see `graph.py`): the baseline arm still verifies, it
just doesn't act on the result, which is what makes "before the verifier
existed" a measurable arm rather than a hypothetical.

`finalize_node` is where the two modes actually diverge: `mode="full"` strips
UNSUPPORTED/CONTRADICTED claims and flags PARTIALLY_SUPPORTED ones before
publishing; `mode="baseline"` publishes every claim the writer drafted,
unfiltered — reproducing exactly what a planner+researcher+writer system
would have shipped before a verifier existed. The `verification_summary`
attached by `verifier_node` is identical in shape either way, which is what
`scripts/compare_before_after.py` diffs.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..config import SETTINGS
from ..state import Claim, Reference, Replace, Report, ReportSection, RunState, VerificationLabel
from ..verify.verifier import Verifier


def verifier_node(state: RunState) -> dict[str, Any]:
    t0 = time.perf_counter()
    claims = state.get("claims", {})
    sources = state.get("sources", {})

    verifier = Verifier()
    run = verifier.verify_all(list(claims.values()), sources, attach=True)
    summary = run.summary()

    return {
        # `attach=True` mutated the Claim objects already in `claims` in place
        # (set .verification, appended grounded EvidenceSpans); `Replace`
        # keeps that the authoritative claim set for this pass.
        "claims": Replace(claims),
        "verification_summary": summary,
        "trace": [{"node": "verifier", **summary, "duration_ms": round((time.perf_counter() - t0) * 1000, 1)}],
    }


def should_revise(state: RunState) -> str:
    claims = state.get("claims", {})
    revision_count = state.get("revision_count", 0)
    max_revisions = state.get("max_revisions", SETTINGS.graph.max_revisions)

    unresolved = any(
        c.verification is not None and not c.verification.is_publishable for c in claims.values()
    )
    if unresolved and revision_count < max_revisions:
        return "revise"
    return "finalize"


def _decisive_judgment(verification) -> Optional[Any]:
    for j in verification.judgments:
        if j.source_id == verification.decisive_source_id:
            return j
    return verification.judgments[0] if verification.judgments else None


def _build_revision_feedback(claims: dict[str, Claim]) -> list[dict[str, Any]]:
    """One entry per rejected claim: what was said, what the verifier decided, and why.

    Keyed by claim *text*, not id — the writer produces a fresh `Claim` (fresh
    id) on every pass, so text is the only stable handle a re-draft can use to
    recognise "this is the same assertion I made last time".
    """
    feedback: list[dict[str, Any]] = []
    for claim in claims.values():
        verification = claim.verification
        if verification is None or verification.is_publishable:
            continue
        decisive = _decisive_judgment(verification)
        feedback.append(
            {
                "text": claim.text,
                "section": claim.section,
                "label": verification.label.value,
                "rationale": (decisive.rationale if decisive else "") or "No evidence was found for this claim.",
                "source_ids": claim.source_ids,
            }
        )
    return feedback


def revise_node(state: RunState) -> dict[str, Any]:
    """Bump the revision counter, collect rejected-claim feedback, loop back to the writer.

    `_build_revision_feedback` turns each unpublishable claim into a
    (text, label, rationale, source_ids) note. `writer_node` reads it back out
    of `revision_feedback` on the next pass: the LLM path folds it into the
    prompt as an explicit "these were rejected, fix or drop them" instruction,
    and the deterministic fallback uses it to avoid re-emitting the exact
    sentence that was already rejected. Either way, the loop now carries the
    verifier's specific objection forward instead of just retrying blind.
    """
    claims = state.get("claims", {})
    revision_count = state.get("revision_count", 0) + 1
    feedback = _build_revision_feedback(claims)
    return {
        "revision_count": revision_count,
        "revision_feedback": feedback,
        "trace": [{"node": "revise", "revision_count": revision_count, "weak_claims": len(feedback)}],
    }


def finalize_node(state: RunState) -> dict[str, Any]:
    t0 = time.perf_counter()
    topic = state.get("topic", "")
    mode = state.get("mode", "full")
    enforce = mode != "baseline"
    sources = state.get("sources", {})

    claims = sorted(state.get("claims", {}).values(), key=lambda c: (c.section, c.order))
    sections: dict[str, list[Claim]] = {}
    dropped: list[str] = []
    flagged: list[str] = []

    for claim in claims:
        verification = claim.verification
        if enforce and (verification is None or not verification.is_publishable):
            dropped.append(claim.id)
            continue
        if verification is not None and verification.label is VerificationLabel.PARTIALLY_SUPPORTED:
            flagged.append(claim.id)
        sections.setdefault(claim.section or "Report", []).append(claim)

    # Number each distinct source in order of first appearance across the
    # published report, so the reader sees "[1]" the first time a source is
    # cited rather than an opaque id like "src_26fac6fa5c" — readable
    # citations are the whole point of this pass (see `Reference` docstring).
    citation_numbers: dict[str, int] = {}
    references: list[Reference] = []

    def _cite_numbers(source_ids: list[str]) -> list[int]:
        numbers = []
        for sid in source_ids:
            if sid not in citation_numbers:
                citation_numbers[sid] = len(citation_numbers) + 1
                source = sources.get(sid)
                references.append(
                    Reference(
                        number=citation_numbers[sid],
                        source_id=sid,
                        title=(source.title if source and source.title else "") or (source.url if source else sid),
                        url=source.url if source else "",
                    )
                )
            numbers.append(citation_numbers[sid])
        return numbers

    lines = [f"# {topic}\n"]
    report_sections: list[ReportSection] = []
    # Sub-questions frequently retrieve overlapping content (often the exact
    # same sentence), so the paragraph view below dedupes on claim text —
    # merging citation numbers into one bracket — while the per-section
    # bullets stay one-per-claim, since each sub-question's own breakdown is
    # still meant to be complete on its own.
    summary_order: list[str] = []
    summary_seen: dict[str, dict[str, Any]] = {}
    for heading, claim_list in sections.items():
        lines.append(f"## {heading}\n")
        prose_lines = []
        for claim in claim_list:
            marker = " ⚠️" if claim.id in flagged else ""
            numbers = _cite_numbers(claim.source_ids)
            cite = f" [{','.join(str(n) for n in numbers)}]" if numbers else ""
            sentence = f"{claim.text}{marker}{cite}"
            lines.append(f"- {sentence}")
            prose_lines.append(f"- {sentence}")

            entry = summary_seen.get(claim.text)
            if entry is None:
                entry = {"flagged": False, "numbers": []}
                summary_seen[claim.text] = entry
                summary_order.append(claim.text)
            entry["flagged"] = entry["flagged"] or bool(marker)
            for n in numbers:
                if n not in entry["numbers"]:
                    entry["numbers"].append(n)
        report_sections.append(
            ReportSection(heading=heading, claim_ids=[c.id for c in claim_list], prose="\n".join(prose_lines))
        )
        lines.append("")

    summary_sentences = []
    for text in summary_order:
        entry = summary_seen[text]
        marker = " ⚠️" if entry["flagged"] else ""
        cite = f" [{','.join(str(n) for n in entry['numbers'])}]" if entry["numbers"] else ""
        summary_sentences.append(f"{text}{marker}{cite}")
    summary = " ".join(summary_sentences)

    if not sections:
        lines.append("_No claims could be verified sufficiently to publish._\n")
    else:
        lines.insert(1, f"{summary}\n")

    if references:
        lines.append("## Sources\n")
        for ref in references:
            lines.append(f"[{ref.number}] {ref.title}" + (f" — {ref.url}" if ref.url else ""))
        lines.append("")

    report = Report(
        topic=topic,
        title=f"Report: {topic}",
        summary=summary,
        sections=report_sections,
        markdown="\n".join(lines),
        references=references,
        dropped_claim_ids=dropped,
        flagged_claim_ids=flagged,
    )

    return {
        "report": report,
        "trace": [
            {
                "node": "finalize",
                "mode": mode,
                "published_claims": sum(len(v) for v in sections.values()),
                "dropped_claims": len(dropped),
                "flagged_claims": len(flagged),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        ],
    }
