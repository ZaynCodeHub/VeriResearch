"""The Verifier.

Pipeline for a single claim:

    claim
      -> candidate sources (from the claim's own evidence links, plus any source
         retrieved for the same sub-question)
      -> for each source: select the most relevant window of raw text
      -> judge(claim, window)
      -> ground the judge's quote in the source's raw text
      -> calibrate confidence
      -> aggregate across sources into one verdict

Aggregation policy
------------------
Not a simple average. Averaging is wrong here because sources are not
interchangeable observers: one source explicitly contradicting a claim is
decisive in a way that three sources being silent is not.

    1. Any grounded CONTRADICTED at or above `contradiction_threshold` wins.
       Contradiction beats support — if source A supports and source B refutes,
       the claim is disputed and must not ship with a green checkmark.
    2. Else, the strongest SUPPORTED at or above `support_threshold` wins.
    3. Else, if anything reached `partial_threshold`, PARTIALLY_SUPPORTED.
    4. Else UNSUPPORTED.

Rule 1 before rule 2 is the whole ethic of the system: we optimise against false
SUPPORTED, not for a high headline number. It would be trivial to make the
before/after chart look better by putting rule 2 first. It would also make the
tool useless.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from ..config import SETTINGS, VerifierConfig
from ..judges import JudgeBackend, JudgeRequest, describe_backend, get_judge
from ..state import (
    Claim,
    ClaimVerification,
    EvidenceSpan,
    Judgment,
    Source,
    VerificationLabel,
)
from .grounding import ground_quote_in_source, locate_quote

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "is",
    "are", "was", "were", "be", "been", "it", "its", "that", "this", "with",
    "as", "by", "from", "has", "have", "had", "which", "than", "then",
}


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


# --------------------------------------------------------------------------- #
# Evidence window selection
# --------------------------------------------------------------------------- #


def select_evidence_window(claim: str, source: Source, max_chars: int) -> tuple[str, int, int]:
    """Pick the most claim-relevant contiguous window of a source.

    Sources are frequently long. Sending the whole document per claim is
    expensive and measurably worse — judges get distracted by adjacent passages
    and drift toward SUPPORTED on topical overlap alone. We score sentences by
    keyword overlap and expand around the best one until the budget is used, so
    the judge sees a focused excerpt with enough surrounding context to catch
    attribution and hedging.
    """
    text = source.raw_text
    if len(text) <= max_chars:
        return text, 0, len(text)

    # Sentence offsets.
    sentences: list[tuple[int, int, str]] = []
    cursor = 0
    for part in _SENT_SPLIT.split(text):
        if not part:
            continue
        start = text.find(part, cursor)
        if start == -1:
            start = cursor
        end = start + len(part)
        sentences.append((start, end, part))
        cursor = end
    if not sentences:
        return text[:max_chars], 0, min(len(text), max_chars)

    claim_kw = _keywords(claim)
    scores = [
        (len(claim_kw & _keywords(s)) / max(1, len(claim_kw)), i)
        for i, (_, _, s) in enumerate(sentences)
    ]
    _, best_i = max(scores)

    lo = hi = best_i
    start, end = sentences[best_i][0], sentences[best_i][1]
    while end - start < max_chars:
        grew = False
        if hi + 1 < len(sentences) and sentences[hi + 1][1] - start <= max_chars:
            hi += 1
            end = sentences[hi][1]
            grew = True
        if lo - 1 >= 0 and end - sentences[lo - 1][0] <= max_chars:
            lo -= 1
            start = sentences[lo][0]
            grew = True
        if not grew:
            break
    return text[start:end], start, end


# --------------------------------------------------------------------------- #
# Result container
# --------------------------------------------------------------------------- #


@dataclass
class VerificationRun:
    """Everything a verification pass produced, for metrics and tracing."""

    verifications: dict[str, ClaimVerification] = field(default_factory=dict)
    backend: str = ""
    claims_checked: int = 0
    judge_calls: int = 0
    ungrounded_quotes: int = 0
    duration_ms: float = 0.0

    def label_counts(self) -> dict[str, int]:
        counts = {label.value: 0 for label in VerificationLabel}
        for v in self.verifications.values():
            counts[v.label.value] += 1
        return counts

    def supported_rate(self) -> float:
        """THE key metric: fraction of claims independently verified SUPPORTED."""
        if not self.verifications:
            return 0.0
        n = sum(1 for v in self.verifications.values() if v.label is VerificationLabel.SUPPORTED)
        return n / len(self.verifications)

    def publishable_rate(self) -> float:
        if not self.verifications:
            return 0.0
        n = sum(1 for v in self.verifications.values() if v.is_publishable)
        return n / len(self.verifications)

    def mean_confidence(self) -> float:
        if not self.verifications:
            return 0.0
        return sum(v.confidence for v in self.verifications.values()) / len(self.verifications)

    def summary(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "claims_checked": self.claims_checked,
            "judge_calls": self.judge_calls,
            "ungrounded_quotes": self.ungrounded_quotes,
            "supported_rate": round(self.supported_rate(), 4),
            "publishable_rate": round(self.publishable_rate(), 4),
            "mean_confidence": round(self.mean_confidence(), 4),
            "label_counts": self.label_counts(),
            "duration_ms": round(self.duration_ms, 1),
        }


# --------------------------------------------------------------------------- #
# Verifier
# --------------------------------------------------------------------------- #


class Verifier:
    def __init__(
        self,
        judge: Optional[JudgeBackend] = None,
        config: Optional[VerifierConfig] = None,
    ) -> None:
        self.config = config or SETTINGS.verifier
        self.judge = judge or get_judge(self.config.backend)
        self.backend_name = describe_backend(self.judge)

    # -- one (claim, source) pair ------------------------------------------- #

    def verify_claim_against_source(self, claim: Claim, source: Source) -> Judgment:
        window, win_start, _ = select_evidence_window(
            claim.text, source, self.config.evidence_window_chars
        )
        verdict = self.judge.judge(
            JudgeRequest(
                claim=claim.text,
                evidence=window,
                claim_id=claim.id,
                source_id=source.id,
            )
        )

        # Ground the judge's quote against the FULL source text, not just the
        # window — a judge quoting accurately from outside the window is still
        # quoting accurately.
        grounding = locate_quote(verdict.quoted_span, source.raw_text) if verdict.quoted_span else None

        confidence = verdict.confidence
        grounded = True
        if verdict.quoted_span:
            if grounding and grounding.grounded:
                confidence *= grounding.confidence_multiplier
            else:
                grounded = False
                confidence *= self.config.ungrounded_penalty
        elif verdict.label is VerificationLabel.SUPPORTED:
            # Claiming support without citing anything is not support.
            grounded = False
            confidence *= self.config.ungrounded_penalty

        return Judgment(
            claim_id=claim.id,
            source_id=source.id,
            label=verdict.label,
            confidence=max(0.0, min(1.0, confidence)),
            rationale=verdict.rationale,
            quoted_span=verdict.quoted_span,
            grounded=grounded,
            backend=self.backend_name,
            samples=getattr(self.judge, "samples", 1),
            latency_ms=verdict.latency_ms,
            raw_response=verdict.raw_response,
        )

    # -- aggregation --------------------------------------------------------- #

    def aggregate(self, claim_id: str, judgments: list[Judgment]) -> ClaimVerification:
        if not judgments:
            return ClaimVerification(
                claim_id=claim_id,
                label=VerificationLabel.UNSUPPORTED,
                confidence=0.95,
                judgments=[],
                aggregation_rule="no-evidence",
            )

        cfg = self.config

        contradictions = [
            j for j in judgments
            if j.label is VerificationLabel.CONTRADICTED
            and j.grounded
            and j.confidence >= cfg.contradiction_threshold
        ]
        if contradictions:
            best = max(contradictions, key=lambda j: j.confidence)
            return ClaimVerification(
                claim_id=claim_id, label=VerificationLabel.CONTRADICTED,
                confidence=best.confidence, judgments=judgments,
                decisive_source_id=best.source_id,
                aggregation_rule="contradiction-override",
            )

        supports = [
            j for j in judgments
            if j.label is VerificationLabel.SUPPORTED and j.confidence >= cfg.support_threshold
        ]
        if supports:
            best = max(supports, key=lambda j: j.confidence)
            # Independent corroboration is worth something, but cap the bonus:
            # three sources copying one press release are not three sources.
            bonus = min(0.06, 0.03 * (len(supports) - 1))
            return ClaimVerification(
                claim_id=claim_id, label=VerificationLabel.SUPPORTED,
                confidence=min(1.0, best.confidence + bonus), judgments=judgments,
                decisive_source_id=best.source_id,
                aggregation_rule=f"support-max(n={len(supports)})",
            )

        partials = [
            j for j in judgments
            if (
                j.label is VerificationLabel.PARTIALLY_SUPPORTED
                or j.label is VerificationLabel.SUPPORTED  # support below threshold
            )
            and j.confidence >= cfg.partial_threshold
        ]
        if partials:
            best = max(partials, key=lambda j: j.confidence)
            return ClaimVerification(
                claim_id=claim_id, label=VerificationLabel.PARTIALLY_SUPPORTED,
                confidence=best.confidence, judgments=judgments,
                decisive_source_id=best.source_id,
                aggregation_rule="partial-max",
            )

        best = max(judgments, key=lambda j: j.confidence)
        return ClaimVerification(
            claim_id=claim_id, label=VerificationLabel.UNSUPPORTED,
            confidence=best.confidence, judgments=judgments,
            decisive_source_id=best.source_id,
            aggregation_rule="fallthrough-unsupported",
        )

    # -- one claim ----------------------------------------------------------- #

    def verify_claim(self, claim: Claim, sources: dict[str, Source]) -> ClaimVerification:
        candidates = [sources[sid] for sid in claim.source_ids if sid in sources]
        judgments = [self.verify_claim_against_source(claim, s) for s in candidates]
        return self.aggregate(claim.id, judgments)

    # -- a whole draft ------------------------------------------------------- #

    def verify_all(
        self,
        claims: Iterable[Claim],
        sources: dict[str, Source],
        attach: bool = True,
    ) -> VerificationRun:
        t0 = time.perf_counter()
        run = VerificationRun(backend=self.backend_name)

        for claim in claims:
            verification = self.verify_claim(claim, sources)
            run.verifications[claim.id] = verification
            run.claims_checked += 1
            run.judge_calls += len(verification.judgments)
            run.ungrounded_quotes += sum(1 for j in verification.judgments if not j.grounded)

            if attach:
                claim.verification = verification
                # Promote the decisive grounded quote to a citable EvidenceSpan
                # so the UI can highlight the exact checked range.
                for j in verification.judgments:
                    if j.grounded and j.quoted_span and j.source_id in sources:
                        _, span = ground_quote_in_source(j.quoted_span, sources[j.source_id])
                        if span and not any(
                            e.source_id == span.source_id and e.char_start == span.char_start
                            for e in claim.evidence
                        ):
                            claim.evidence.append(span)

        run.duration_ms = (time.perf_counter() - t0) * 1000
        return run
