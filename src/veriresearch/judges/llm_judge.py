"""Grok-as-judge: the primary backend for real (non-demo) runs.

The prompt requires a verbatim `quoted_span` for any SUPPORTED/PARTIALLY_SUPPORTED/
CONTRADICTED verdict. That quote is not trusted on its own — verify/grounding.py
re-locates it in the source text after the fact, so a judge that asserts support
but doesn't (or can't) quote the exact sentence gets caught, not believed. See
`FABRICATED_JUDGE_RESPONSE` in fixtures.py for the guardrail this defends.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from ..llm import LLMClient
from ..state import VerificationLabel
from . import JudgeRequest, JudgeVerdict

SYSTEM_PROMPT = """You are a strict fact-verification judge. You are given a CLAIM and an \
EVIDENCE passage taken verbatim from one source document. Decide whether the evidence \
supports the claim.

Respond with ONLY a JSON object, no markdown fences, no commentary:
{
  "label": "SUPPORTED" | "PARTIALLY_SUPPORTED" | "UNSUPPORTED" | "CONTRADICTED",
  "confidence": <float 0.0-1.0>,
  "quoted_span": "<verbatim substring copied from EVIDENCE that justifies the label, \
or empty string if the label is UNSUPPORTED>",
  "rationale": "<one sentence>"
}

Rules:
- "quoted_span" MUST be copied character-for-character from EVIDENCE. Do not \
paraphrase, summarize, or combine text from different parts of EVIDENCE. If you \
cannot find a real substring that justifies your label, do not fabricate one — \
lower your label instead.
- SUPPORTED: every substantive element of the claim is stated in EVIDENCE.
- PARTIALLY_SUPPORTED: some elements are stated, others are not addressed.
- UNSUPPORTED: EVIDENCE does not address the claim.
- CONTRADICTED: EVIDENCE asserts something incompatible with the claim.
"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


class LLMJudge:
    def __init__(self, client: LLMClient, model: str = "", samples: int = 1) -> None:
        self.client = client
        self.model = model or getattr(client, "model", "unknown")
        self.samples = max(1, samples)
        self.name = f"llm:{self.model}"

    def _prompt(self, request: JudgeRequest) -> str:
        return f"CLAIM:\n{request.claim}\n\nEVIDENCE:\n{request.evidence}\n"

    def _one_pass(self, request: JudgeRequest) -> JudgeVerdict:
        t0 = time.perf_counter()
        response = self.client.complete(SYSTEM_PROMPT, self._prompt(request), max_tokens=400)
        latency_ms = (time.perf_counter() - t0) * 1000
        data = _extract_json(response.text)

        if data is None:
            return JudgeVerdict(
                label=VerificationLabel.UNSUPPORTED,
                confidence=0.2,
                rationale=f"Judge response was not parseable JSON: {response.text[:200]!r}",
                quoted_span="",
                latency_ms=latency_ms,
                raw_response=response.text,
            )

        try:
            label = VerificationLabel(str(data.get("label", "")).upper())
        except ValueError:
            label = VerificationLabel.UNSUPPORTED

        confidence = data.get("confidence", 0.5)
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.5

        return JudgeVerdict(
            label=label,
            confidence=confidence,
            rationale=str(data.get("rationale", "")),
            quoted_span=str(data.get("quoted_span", "") or ""),
            latency_ms=latency_ms,
            raw_response=response.text,
        )

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        if self.samples == 1:
            return self._one_pass(request)

        passes = [self._one_pass(request) for _ in range(self.samples)]
        votes: dict[VerificationLabel, list[JudgeVerdict]] = {}
        for p in passes:
            votes.setdefault(p.label, []).append(p)
        winning_label, winning_passes = max(votes.items(), key=lambda kv: len(kv[1]))
        agreement = len(winning_passes) / len(passes)
        best = max(winning_passes, key=lambda p: p.confidence)
        return JudgeVerdict(
            label=winning_label,
            confidence=best.confidence * (0.7 + 0.3 * agreement),
            rationale=f"{best.rationale} (self-consistency {len(winning_passes)}/{len(passes)})",
            quoted_span=best.quoted_span,
            latency_ms=sum(p.latency_ms for p in passes),
            raw_response=best.raw_response,
        )
