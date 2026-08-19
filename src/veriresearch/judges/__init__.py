"""Judge backends: pluggable implementations of "does this evidence support this claim".

Every backend implements the same two-method contract (`JudgeBackend`) so the
Verifier's aggregation policy (verify/verifier.py) never needs to know which
backend produced a `Judgment` — it only needs a label, a confidence, and
(ideally) a verbatim quote to ground.

    heuristic  offline, deterministic, zero cost, zero dependencies — the
               default when no GROK_API_KEY is set, so the repo runs
               immediately after clone.
    llm        Grok-as-judge. The primary backend for real use.
    nli        Optional cross-encoder entailment model (transformers). Can
               classify but cannot quote — see judges/nli.py for why that
               matters here.
    cascade    heuristic first pass, escalate to llm only on low-confidence
               or PARTIALLY_SUPPORTED verdicts, to cut judge-call cost on the
               easy majority of claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from ..config import SETTINGS
from ..state import VerificationLabel


@dataclass
class JudgeRequest:
    """What a judge needs to render a verdict on one (claim, evidence) pair."""

    claim: str
    evidence: str
    claim_id: str = ""
    source_id: str = ""


@dataclass
class JudgeVerdict:
    """What every judge backend must produce, regardless of how it got there."""

    label: VerificationLabel
    confidence: float
    rationale: str = ""
    quoted_span: str = ""
    latency_ms: float = 0.0
    raw_response: Optional[str] = None


@runtime_checkable
class JudgeBackend(Protocol):
    name: str
    samples: int

    def judge(self, request: JudgeRequest) -> JudgeVerdict: ...


def describe_backend(judge: JudgeBackend) -> str:
    return getattr(judge, "name", judge.__class__.__name__)


def get_judge(backend: Optional[str] = None) -> JudgeBackend:
    """Resolve a backend name (or None/"auto") to a live judge instance.

    "auto" picks `llm` when `GROK_API_KEY` is set and `heuristic`
    otherwise, which is what makes `python scripts/demo_verifier.py` and the
    test suite runnable with zero configuration.
    """
    resolved = (backend or SETTINGS.verifier.backend or "auto").lower()

    if resolved == "auto":
        resolved = "llm" if SETTINGS.planner.has_llm else "heuristic"

    if resolved == "heuristic":
        from .heuristic import HeuristicJudge

        return HeuristicJudge()

    if resolved == "llm":
        if not SETTINGS.planner.has_llm:
            raise RuntimeError(
                "backend='llm' requires GROK_API_KEY. Use backend='heuristic' "
                "(or leave backend unset / 'auto') to run without one."
            )
        from ..llm import GrokClient
        from .llm_judge import LLMJudge

        client = GrokClient(model=SETTINGS.verifier.llm_model)
        return LLMJudge(client=client, model=SETTINGS.verifier.llm_model, samples=SETTINGS.verifier.llm_samples)

    if resolved == "nli":
        from .nli import NLIJudge

        return NLIJudge()

    if resolved == "cascade":
        from .cascade import CascadeJudge

        return CascadeJudge()

    raise ValueError(f"Unknown judge backend: {resolved!r} (want heuristic | llm | nli | cascade | auto)")
