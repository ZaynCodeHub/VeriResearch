"""Optional cross-encoder NLI backend (entailment/neutral/contradiction).

Included because the brief calls for "an NLI/entailment check or LLM-as-judge,"
and it's worth being honest about the tradeoff rather than hiding it: an NLI
model gives a fast, cheap three-way label, but it cannot point at *which* span
of the evidence it used — there's no quote to ground. Every SUPPORTED verdict
from this backend is therefore treated by the Verifier as "asserted support
without a citation" and takes the `ungrounded_penalty` (see verify/verifier.py
and config.py). That's a deliberate consequence of the auditability
requirement, not a bug: a verdict this system cannot show you the evidence for
is not one it will let ship as a green checkmark.

Requires `transformers` + a backend (torch); not installed by default, so
`get_judge("nli")` raises a clear error rather than failing the whole package
import if it's absent.
"""

from __future__ import annotations

import time

from ..state import VerificationLabel
from . import JudgeRequest, JudgeVerdict

DEFAULT_MODEL = "roberta-large-mnli"


class NLIJudge:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        try:
            from transformers import pipeline
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "backend='nli' requires `pip install transformers torch`. "
                "Use backend='heuristic' or 'llm' otherwise."
            ) from exc

        self._pipe = pipeline("text-classification", model=model_name, top_k=None)
        self.model_name = model_name
        self.name = f"nli:{model_name}"
        self.samples = 1

    def judge(self, request: JudgeRequest) -> JudgeVerdict:
        t0 = time.perf_counter()
        raw = self._pipe({"text": request.evidence, "text_pair": request.claim})
        scores = {r["label"].upper(): r["score"] for r in raw}
        entail = scores.get("ENTAILMENT", 0.0)
        contra = scores.get("CONTRADICTION", 0.0)
        neutral = scores.get("NEUTRAL", 0.0)
        latency_ms = (time.perf_counter() - t0) * 1000

        if contra >= entail and contra >= neutral:
            label, confidence = VerificationLabel.CONTRADICTED, contra
        elif entail >= 0.60:
            label, confidence = VerificationLabel.SUPPORTED, entail
        elif entail >= 0.30:
            label, confidence = VerificationLabel.PARTIALLY_SUPPORTED, entail
        else:
            label, confidence = VerificationLabel.UNSUPPORTED, neutral

        return JudgeVerdict(
            label=label,
            confidence=confidence,
            rationale=f"NLI scores: entailment={entail:.2f} contradiction={contra:.2f} neutral={neutral:.2f}",
            quoted_span="",  # no span-level attribution — see module docstring
            latency_ms=latency_ms,
            raw_response=str(scores),
        )
