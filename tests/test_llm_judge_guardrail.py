"""The grounding guardrail: a judge that fabricates its own supporting quote
must not be able to ship a claim as SUPPORTED. This is the same check
`scripts/demo_verifier.py` runs interactively; here it's pinned as a test.
"""

import json

from veriresearch.fixtures import DEMO_SOURCES, FABRICATED_JUDGE_RESPONSE, HALLUCINATED_QUOTE_CLAIM
from veriresearch.judges.llm_judge import LLMJudge
from veriresearch.llm import StubClient
from veriresearch.state import VerificationLabel
from veriresearch.verify.verifier import Verifier


def test_fabricated_quote_demotes_claim_out_of_supported():
    judge = LLMJudge(client=StubClient(default=FABRICATED_JUDGE_RESPONSE), samples=1)
    verifier = Verifier(judge=judge)

    verification = verifier.verify_claim(HALLUCINATED_QUOTE_CLAIM, DEMO_SOURCES)
    judgment = verification.judgments[0]

    assert not judgment.grounded
    assert judgment.confidence < 0.5  # penalised well below support_threshold
    assert verification.label is not VerificationLabel.SUPPORTED


def test_grounded_quote_is_trusted_at_full_confidence():
    real_quote = "It is the largest and most powerful space telescope ever built."
    response = json.dumps(
        {
            "label": "SUPPORTED",
            "confidence": 0.9,
            "quoted_span": real_quote,
            "rationale": "stated directly",
        }
    )
    judge = LLMJudge(client=StubClient(default=response), samples=1)
    verifier = Verifier(judge=judge)

    verification = verifier.verify_claim(HALLUCINATED_QUOTE_CLAIM, DEMO_SOURCES)
    judgment = verification.judgments[0]

    assert judgment.grounded
    assert judgment.confidence == 0.9  # exact-match grounding: multiplier is 1.0
    assert verification.label is VerificationLabel.SUPPORTED


def test_unparseable_response_fails_safe_to_unsupported():
    from veriresearch.judges import JudgeRequest

    judge = LLMJudge(client=StubClient(default="not json at all"), samples=1)
    result = judge.judge(JudgeRequest(claim="anything", evidence="anything"))
    assert result.label is VerificationLabel.UNSUPPORTED
    assert result.confidence < 0.5
