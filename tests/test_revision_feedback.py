from veriresearch.nodes.verifier_node import _build_revision_feedback
from veriresearch.nodes.writer import _deterministic_draft
from veriresearch.state import (
    Claim,
    ClaimVerification,
    EvidenceSpan,
    Judgment,
    Source,
    SubQuestion,
    VerificationLabel,
)


def _rejected_claim(text: str, label: VerificationLabel, rationale: str, source_id: str) -> Claim:
    judgment = Judgment(
        claim_id="clm_x", source_id=source_id, label=label, confidence=0.8, rationale=rationale
    )
    verification = ClaimVerification(
        claim_id="clm_x",
        label=label,
        confidence=0.8,
        judgments=[judgment],
        decisive_source_id=source_id,
        aggregation_rule="contradiction-override",
    )
    evidence = [EvidenceSpan(source_id=source_id, char_start=0, char_end=len(text), text=text)]
    claim = Claim(text=text, section="Section", evidence=evidence)
    claim.verification = verification
    return claim


def test_build_revision_feedback_skips_publishable_claims():
    supported = _rejected_claim("Fine claim.", VerificationLabel.SUPPORTED, "matches", "src_a")
    feedback = _build_revision_feedback({supported.id: supported})
    assert feedback == []


def test_build_revision_feedback_captures_rejection_reason():
    rejected = _rejected_claim(
        "JWST orbits Earth.", VerificationLabel.CONTRADICTED, "polarity conflict", "corpus_jwst"
    )
    feedback = _build_revision_feedback({rejected.id: rejected})
    assert len(feedback) == 1
    entry = feedback[0]
    assert entry["text"] == "JWST orbits Earth."
    assert entry["label"] == "CONTRADICTED"
    assert entry["rationale"] == "polarity conflict"
    assert entry["source_ids"] == ["corpus_jwst"]


def test_deterministic_draft_avoids_reproducing_rejected_negation():
    """Without feedback, the negation perturbation is deterministic and fires
    every pass. With the exact negated sentence passed in `avoid_texts` (as
    revise_node would after a rejection), the next draft must not reproduce
    it verbatim — this is the fix for the stated 'revise loop can reproduce
    the same claims verbatim' limitation."""
    source = Source(
        id="src_jwst",
        url="local-corpus://jwst",
        raw_text=(
            "JWST launched in 2021. "
            "JWST does not orbit Earth; it orbits the Sun near L2. "
            "It observes primarily in the infrared."
        ),
        retrieved_by="sq_1",
    )
    sq = SubQuestion(id="sq_1", text="Where is JWST?")
    sources = {source.id: source}

    perturbed = "JWST does orbit Earth; it orbits the Sun near L2."
    original = "JWST does not orbit Earth; it orbits the Sun near L2."

    first_draft = _deterministic_draft([sq], sources)
    assert perturbed in first_draft

    healed_draft = _deterministic_draft([sq], sources, avoid_texts=frozenset({perturbed}))
    assert perturbed not in healed_draft
    assert original in healed_draft
