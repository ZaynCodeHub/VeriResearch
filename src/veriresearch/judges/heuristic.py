"""Offline entailment heuristic — no network, no API key, deterministic.

This is not a substitute for an LLM or NLI judge; it is what makes the repo
runnable with zero configuration (README's "no API keys" quickstart) and what
the test suite runs against so CI has no network dependency. It scores
keyword overlap between the claim and each evidence sentence, then applies two
cheap-but-real contradiction signals — polarity mismatch (a negation on one
side but not the other) and numeric mismatch (different years/counts in an
otherwise-matching sentence) — before falling back to overlap-only
support/partial/unsupported.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from ..state import VerificationLabel
from . import JudgeRequest, JudgeVerdict

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "is",
    "are", "was", "were", "be", "been", "it", "its", "that", "this", "with",
    "as", "by", "from", "has", "have", "had", "which", "than", "then", "does",
    "do", "did",
}
_NEGATIONS = (
    "not ", "n't", "never ", "no longer", "cannot", "isn't", "wasn't",
    "doesn't", "didn't", "does not", "did not", "is not", "was not",
    "false", "incorrect", "no evidence",
)
_NUMBER = re.compile(r"\b\d{3,4}\b")


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def _sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text) if s.strip()]


def _has_negation(text: str) -> bool:
    low = text.lower()
    return any(neg in low for neg in _NEGATIONS)


@dataclass
class HeuristicJudge:
    name: str = "heuristic"
    samples: int = 1

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        t0 = time.perf_counter()
        claim_kw = _keywords(request.claim)
        sentences = _sentences(request.evidence) or [request.evidence]

        best_sentence, best_ratio = "", 0.0
        for sent in sentences:
            sent_kw = _keywords(sent)
            ratio = len(claim_kw & sent_kw) / max(1, len(claim_kw))
            if ratio > best_ratio:
                best_ratio, best_sentence = ratio, sent

        claim_negated = _has_negation(request.claim)
        sentence_negated = _has_negation(best_sentence)
        polarity_mismatch = best_ratio > 0 and claim_negated != sentence_negated

        claim_nums = set(_NUMBER.findall(request.claim))
        sent_nums = set(_NUMBER.findall(best_sentence))
        numeric_mismatch = bool(claim_nums) and bool(sent_nums) and claim_nums.isdisjoint(sent_nums)

        contradicted = best_ratio >= 0.35 and (polarity_mismatch or numeric_mismatch)

        if contradicted:
            label = VerificationLabel.CONTRADICTED
            confidence = min(0.95, 0.55 + 0.35 * best_ratio)
            quote = best_sentence.strip()
            rationale = (
                "Keyword overlap is high but the source's polarity/figures conflict "
                "with the claim's." if polarity_mismatch else
                "Keyword overlap is high but the source cites different figures than the claim."
            )
        elif best_ratio >= 0.70:
            label = VerificationLabel.SUPPORTED
            confidence = min(0.97, 0.55 + 0.40 * best_ratio)
            quote = best_sentence.strip()
            rationale = "High keyword overlap with a single source sentence, no polarity/figure conflict."
        elif best_ratio >= 0.35:
            label = VerificationLabel.PARTIALLY_SUPPORTED
            confidence = min(0.85, 0.35 + 0.35 * best_ratio)
            quote = best_sentence.strip()
            rationale = "Some elements of the claim match the source; others are not addressed in this sentence."
        else:
            label = VerificationLabel.UNSUPPORTED
            confidence = min(0.90, 0.60 + 0.35 * (1 - best_ratio))
            quote = ""
            rationale = "No source sentence shares enough of the claim's key terms to support it."

        return JudgeVerdict(
            label=label,
            confidence=confidence,
            rationale=rationale,
            quoted_span=quote,
            latency_ms=(time.perf_counter() - t0) * 1000,
            raw_response=None,
        )
