"""Aggregation policy: verify/verifier.py's Verifier.aggregate.

Not a simple average — contradiction beats support, support caps its
multi-source bonus, and the ordering (contradiction -> support -> partial ->
fallthrough) is the whole point of the system. See the module docstring on
verify/verifier.py for the rationale.
"""

from veriresearch.judges.heuristic import HeuristicJudge
from veriresearch.state import Judgment, VerificationLabel
from veriresearch.verify.verifier import Verifier


def _judgment(label: VerificationLabel, confidence: float, source_id: str = "src_1", grounded: bool = True) -> Judgment:
    return Judgment(
        claim_id="clm_1",
        source_id=source_id,
        label=label,
        confidence=confidence,
        grounded=grounded,
        backend="test",
    )


def test_no_evidence_is_unsupported_high_confidence():
    verifier = Verifier(judge=HeuristicJudge())
    result = verifier.aggregate("clm_1", [])
    assert result.label is VerificationLabel.UNSUPPORTED
    assert result.aggregation_rule == "no-evidence"


def test_contradiction_beats_support_even_when_support_is_stronger():
    verifier = Verifier(judge=HeuristicJudge())
    judgments = [
        _judgment(VerificationLabel.SUPPORTED, 0.95, source_id="src_a"),
        _judgment(VerificationLabel.CONTRADICTED, 0.60, source_id="src_b"),
    ]
    result = verifier.aggregate("clm_1", judgments)
    assert result.label is VerificationLabel.CONTRADICTED
    assert result.aggregation_rule == "contradiction-override"
    assert result.decisive_source_id == "src_b"


def test_contradiction_below_threshold_does_not_override():
    verifier = Verifier(judge=HeuristicJudge())
    judgments = [
        _judgment(VerificationLabel.SUPPORTED, 0.90, source_id="src_a"),
        _judgment(VerificationLabel.CONTRADICTED, 0.10, source_id="src_b"),  # below contradiction_threshold
    ]
    result = verifier.aggregate("clm_1", judgments)
    assert result.label is VerificationLabel.SUPPORTED


def test_ungrounded_contradiction_does_not_override():
    verifier = Verifier(judge=HeuristicJudge())
    judgments = [
        _judgment(VerificationLabel.SUPPORTED, 0.90, source_id="src_a"),
        _judgment(VerificationLabel.CONTRADICTED, 0.95, source_id="src_b", grounded=False),
    ]
    result = verifier.aggregate("clm_1", judgments)
    assert result.label is VerificationLabel.SUPPORTED


def test_multi_source_support_bonus_is_capped():
    verifier = Verifier(judge=HeuristicJudge())
    judgments = [_judgment(VerificationLabel.SUPPORTED, 0.90, source_id=f"src_{i}") for i in range(5)]
    result = verifier.aggregate("clm_1", judgments)
    assert result.label is VerificationLabel.SUPPORTED
    # base 0.90 + capped bonus (min(0.06, 0.03*(n-1))) should not exceed 0.96
    assert result.confidence <= 0.96 + 1e-9


def test_partial_fallthrough_when_nothing_reaches_support_threshold():
    verifier = Verifier(judge=HeuristicJudge())
    judgments = [_judgment(VerificationLabel.PARTIALLY_SUPPORTED, 0.50)]
    result = verifier.aggregate("clm_1", judgments)
    assert result.label is VerificationLabel.PARTIALLY_SUPPORTED
    assert result.aggregation_rule == "partial-max"


def test_fallthrough_unsupported_when_everything_is_weak():
    verifier = Verifier(judge=HeuristicJudge())
    judgments = [_judgment(VerificationLabel.UNSUPPORTED, 0.20)]
    result = verifier.aggregate("clm_1", judgments)
    assert result.label is VerificationLabel.UNSUPPORTED
    assert result.aggregation_rule == "fallthrough-unsupported"
