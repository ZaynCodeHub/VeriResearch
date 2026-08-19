"""Hardcoded claims/sources for `scripts/demo_verifier.py` and the test suite.

This is the "2-3 test claims" starting point: one real source document, one
claim per verification label, and a fifth claim used to demonstrate the
grounding guardrail (verify/grounding.py) catching a judge that fabricates its
own supporting quote. Everything here is designed to work with the offline
`HeuristicJudge` so the demo needs no API key.
"""

from __future__ import annotations

import json

from .state import Claim, EvidenceSpan, Source, VerificationLabel

JWST_SOURCE = Source(
    id="src_jwst_nasa",
    url="https://www.nasa.gov/mission/webb/facts",
    title="James Webb Space Telescope — mission facts",
    search_query="James Webb Space Telescope facts",
    retrieved_by="sq_demo",
    raw_text=(
        "The James Webb Space Telescope (JWST) launched on December 25, 2021, from "
        "Europe's Spaceport near Kourou, French Guiana, atop an Ariane 5 rocket. "
        "It is the largest and most powerful space telescope ever built. "
        "Its primary mirror is 6.5 meters in diameter, made of 18 hexagonal "
        "gold-coated beryllium segments. "
        "JWST observes primarily in the infrared, which lets it see through dust "
        "clouds and detect the faint light of the earliest galaxies. "
        "Unlike Hubble, which orbits Earth at low altitude, JWST does not orbit "
        "Earth; instead it orbits the Sun near the second Lagrange point (L2), "
        "about 1.5 million kilometers away. "
        "The telescope is a collaboration between NASA, the European Space Agency, "
        "and the Canadian Space Agency. "
        "Its first full-colour science images were released on July 12, 2022."
    ),
)

DEMO_SOURCES: dict[str, Source] = {JWST_SOURCE.id: JWST_SOURCE}


def _evidence_from_full_source(source: Source) -> EvidenceSpan:
    """Pre-verification candidate evidence: 'this source was retrieved for this
    claim's sub-question', not yet a grounded quote. The Verifier replaces/
    supplements this with a precise grounded span once it judges the claim."""
    return EvidenceSpan(
        source_id=source.id,
        char_start=0,
        char_end=len(source.raw_text),
        text=source.raw_text,
        locator="full-source (pre-verification candidate)",
    )


SUPPORTED_CLAIM = Claim(
    id="clm_demo_supported",
    text="The James Webb Space Telescope launched on December 25, 2021.",
    section="demo",
    evidence=[_evidence_from_full_source(JWST_SOURCE)],
)

PARTIALLY_SUPPORTED_CLAIM = Claim(
    id="clm_demo_partial",
    text="JWST's primary mirror consists of 18 hexagonal segments and cost $10 billion to build.",
    section="demo",
    evidence=[_evidence_from_full_source(JWST_SOURCE)],
)

UNSUPPORTED_CLAIM = Claim(
    id="clm_demo_unsupported",
    text="JWST discovered liquid water on a moon of Saturn in 2023.",
    section="demo",
    evidence=[_evidence_from_full_source(JWST_SOURCE)],
)

CONTRADICTED_CLAIM = Claim(
    id="clm_demo_contradicted",
    text="JWST orbits Earth at low altitude, the same way the Hubble Space Telescope does.",
    section="demo",
    evidence=[_evidence_from_full_source(JWST_SOURCE)],
)

# (claim, expected_label, why-this-is-the-expected-label)
DEMO_CLAIMS: list[tuple[Claim, VerificationLabel, str]] = [
    (
        SUPPORTED_CLAIM,
        VerificationLabel.SUPPORTED,
        "Stated verbatim in the source: launch date and vehicle both match.",
    ),
    (
        PARTIALLY_SUPPORTED_CLAIM,
        VerificationLabel.PARTIALLY_SUPPORTED,
        "The mirror composition is stated; the $10B cost figure is never mentioned.",
    ),
    (
        UNSUPPORTED_CLAIM,
        VerificationLabel.UNSUPPORTED,
        "The source says nothing about Saturn, its moons, or water detection.",
    ),
    (
        CONTRADICTED_CLAIM,
        VerificationLabel.CONTRADICTED,
        "The source explicitly says JWST does NOT orbit Earth like Hubble does — "
        "it orbits the Sun near L2.",
    ),
]

# --------------------------------------------------------------------------- #
# Grounding guardrail: a judge that fabricates its own supporting quote.
# --------------------------------------------------------------------------- #

HALLUCINATED_QUOTE_CLAIM = Claim(
    id="clm_demo_hallucinated_quote",
    text="JWST's mirror segments are coated in gold.",
    section="demo",
    evidence=[_evidence_from_full_source(JWST_SOURCE)],
)

# A rigged LLM response: correct-looking JSON, high confidence, SUPPORTED —
# but the quoted_span does not appear anywhere in JWST_SOURCE.raw_text. This is
# what "the judge hallucinated its own justification" looks like on the wire.
FABRICATED_JUDGE_RESPONSE = json.dumps(
    {
        "label": "SUPPORTED",
        "confidence": 0.95,
        "quoted_span": (
            "JWST's mirror segments are coated in a solid platinum-iridium alloy "
            "and were assembled entirely by robotic arms while already in orbit."
        ),
        "rationale": "The source clearly states the mirror coating material.",
    }
)
