from veriresearch.judges import JudgeRequest
from veriresearch.judges.heuristic import HeuristicJudge
from veriresearch.state import VerificationLabel

EVIDENCE = (
    "The James Webb Space Telescope (JWST) launched on December 25, 2021, from "
    "Europe's Spaceport near Kourou, French Guiana, atop an Ariane 5 rocket. "
    "Unlike Hubble, which orbits Earth at low altitude, JWST does not orbit "
    "Earth; instead it orbits the Sun near the second Lagrange point (L2)."
)


def test_high_overlap_no_conflict_is_supported():
    judge = HeuristicJudge()
    verdict = judge.judge(JudgeRequest(claim="The James Webb Space Telescope launched on December 25, 2021.", evidence=EVIDENCE))
    assert verdict.label is VerificationLabel.SUPPORTED
    assert verdict.quoted_span in EVIDENCE


def test_low_overlap_is_unsupported():
    judge = HeuristicJudge()
    verdict = judge.judge(JudgeRequest(claim="JWST discovered liquid water on a moon of Saturn.", evidence=EVIDENCE))
    assert verdict.label is VerificationLabel.UNSUPPORTED
    assert verdict.quoted_span == ""


def test_polarity_mismatch_is_contradicted():
    judge = HeuristicJudge()
    verdict = judge.judge(
        JudgeRequest(claim="JWST orbits Earth at low altitude, the same way Hubble does.", evidence=EVIDENCE)
    )
    assert verdict.label is VerificationLabel.CONTRADICTED
    assert verdict.quoted_span in EVIDENCE


def test_quoted_span_is_always_a_verbatim_substring_of_evidence():
    judge = HeuristicJudge()
    for claim in (
        "The James Webb Space Telescope launched in 2021.",
        "JWST orbits Earth at low altitude.",
    ):
        verdict = judge.judge(JudgeRequest(claim=claim, evidence=EVIDENCE))
        if verdict.quoted_span:
            assert verdict.quoted_span in EVIDENCE
