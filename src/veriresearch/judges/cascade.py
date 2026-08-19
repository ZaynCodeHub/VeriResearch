"""Heuristic first pass, escalate to the LLM only when it's unsure.

Most claims in a real draft are either obviously well-supported or obviously
made up; the heuristic gets those right for free. The expensive judge is
reserved for the ambiguous middle, where a keyword-overlap heuristic can't be
trusted: PARTIALLY_SUPPORTED verdicts, and anything below `escalate_below`
confidence. This is the backend to point at in production once cost matters —
`llm` alone is simpler and is what get_judge("auto") picks for correctness-
first demos.
"""

from __future__ import annotations

from ..state import VerificationLabel
from . import JudgeBackend, JudgeRequest, JudgeVerdict
from .heuristic import HeuristicJudge


class CascadeJudge:
    def __init__(self, escalate_below: float = 0.75, llm_judge: JudgeBackend | None = None) -> None:
        self.cheap = HeuristicJudge()
        self.escalate_below = escalate_below
        self._llm_judge = llm_judge  # lazily constructed on first escalation
        self.samples = 1
        self.name = "cascade:heuristic+llm"

    def _llm(self) -> JudgeBackend:
        if self._llm_judge is None:
            from ..config import SETTINGS
            from ..llm import GrokClient
            from .llm_judge import LLMJudge

            self._llm_judge = LLMJudge(
                client=GrokClient(model=SETTINGS.verifier.llm_model),
                model=SETTINGS.verifier.llm_model,
            )
        return self._llm_judge

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        first = self.cheap.judge(request)
        needs_escalation = (
            first.label is VerificationLabel.PARTIALLY_SUPPORTED
            or first.confidence < self.escalate_below
        )
        if not needs_escalation:
            return first

        second = self._llm().judge(request)
        second.rationale = f"[escalated from heuristic: {first.label.value}@{first.confidence:.2f}] {second.rationale}"
        return second
