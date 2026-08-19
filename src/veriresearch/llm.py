"""LLM client used by the planner and the LLM judge, plus a stub for tests.

Kept as a thin protocol rather than importing `openai` at module scope:
`StubClient` needs to satisfy the same interface with zero dependencies so the
test suite and `demo_verifier.py` stay hermetic (no network, no SDK import) by
default. `GrokClient` imports the SDK lazily, on first real call.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional, Protocol


class LLMClient(Protocol):
    def complete(self, system: str, prompt: str, *, max_tokens: int = 1024) -> "LLMResponse": ...


@dataclass
class LLMResponse:
    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class GrokClient:
    """Thin wrapper around xAI's Grok API.

    Grok's API is OpenAI-compatible, so this uses the `openai` SDK pointed at
    xAI's base URL rather than a dedicated xAI SDK — one fewer dependency, and
    the same client shape (`chat.completions.create`) as everything else in
    that ecosystem. Requires `GROK_API_KEY`. The import is deferred into
    `__init__` so that importing `veriresearch.llm` never requires the
    `openai` package to be installed unless this class is actually
    instantiated.
    """

    BASE_URL = "https://api.x.ai/v1"

    def __init__(self, model: str = "grok-4", api_key: Optional[str] = None) -> None:
        try:
            import openai
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "The 'openai' package is required for GrokClient (xAI's API is "
                "OpenAI-compatible). Install it with `pip install openai`, or use "
                "backend='heuristic'."
            ) from exc

        key = api_key or os.getenv("GROK_API_KEY")
        if not key:
            raise RuntimeError("GROK_API_KEY is not set.")
        self.model = model
        self._client = openai.OpenAI(api_key=key, base_url=self.BASE_URL)

    def complete(self, system: str, prompt: str, *, max_tokens: int = 1024) -> LLMResponse:
        t0 = time.perf_counter()
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        text = resp.choices[0].message.content or ""
        latency_ms = (time.perf_counter() - t0) * 1000
        usage = resp.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        from .tracing import log_generation

        log_generation(
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )


class StubClient:
    """Deterministic client for hermetic tests and the fabricated-quote demo.

    Returns `default` for every call regardless of prompt, unless `responses`
    (a list) is supplied, in which case it returns them in order, repeating
    the last one once exhausted. No network, no SDK import, no API key.
    """

    def __init__(self, default: str = "", responses: Optional[list[str]] = None) -> None:
        self.default = default
        self.responses = responses or []
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str, *, max_tokens: int = 1024) -> LLMResponse:
        self.calls.append((system, prompt))
        idx = len(self.calls) - 1
        if self.responses:
            text = self.responses[min(idx, len(self.responses) - 1)]
        else:
            text = self.default
        return LLMResponse(text=text, model="stub", input_tokens=0, output_tokens=0, latency_ms=0.1)
