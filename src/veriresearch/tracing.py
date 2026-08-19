"""Langfuse tracing: per-node cost, latency, and token count, opt-in.

`traced_node` wraps each LangGraph node with a Langfuse span when
`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are set; with no keys it returns
the original function completely unwrapped — the `langfuse` package is never
even imported, so tracing costs nothing (no dependency, no overhead) for the
hermetic/offline path the rest of this project is built around.

Node latency was already being recorded into `RunState["trace"]` before this
file existed (see each node's `duration_ms` trace entry) — that's a
self-contained audit trail with zero dependencies. What Langfuse adds on top
is the cost and token count Grok's API returns, which nothing in
`RunState` captures, plus a hosted trace UI. `GrokClient.complete()`
(llm.py) reports those through `log_generation` below whenever tracing is
active, so a single Langfuse trace shows exactly which node spent how much
and on what.

Not exercised against a live Langfuse project in this environment — no
`LANGFUSE_*` keys were available while building this. The `@observe`/
`update_current_observation` calls below follow the documented langfuse-python
v2 API (https://langfuse.com/docs/sdk/python/decorators); every call is
wrapped so a Langfuse-side failure degrades to a no-op rather than breaking a
run — tracing must never be why a research run fails.
"""

from __future__ import annotations

import functools
import os
from typing import Any, Callable, TypeVar

NodeFn = TypeVar("NodeFn", bound=Callable[..., dict[str, Any]])


def is_configured() -> bool:
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def traced_node(name: str) -> Callable[[NodeFn], NodeFn]:
    """Decorator for a LangGraph node function `(state) -> dict`."""

    def decorator(fn: NodeFn) -> NodeFn:
        if not is_configured():
            return fn

        try:
            from langfuse.decorators import observe
        except ImportError:
            return fn

        observed = observe(name=name, as_type="span")(fn)

        @functools.wraps(fn)
        def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            try:
                return observed(state)
            except Exception:
                # A tracing-layer failure must never take down a research run.
                return fn(state)

        return wrapper  # type: ignore[return-value]

    return decorator


def log_generation(*, model: str, input_tokens: int, output_tokens: int, latency_ms: float) -> None:
    """Attach token usage to the current Langfuse observation, if tracing is active.

    Call this from inside a `GrokClient.complete()` call — it attaches to
    whichever `traced_node` span is currently on the stack, so a single
    Langfuse trace shows exactly which node made which LLM call. No-ops
    silently if tracing isn't configured or the Langfuse call fails.
    """
    if not is_configured():
        return
    try:
        from langfuse.decorators import langfuse_context

        langfuse_context.update_current_observation(
            model=model,
            usage_details={"input": input_tokens, "output": output_tokens},
            metadata={"latency_ms": latency_ms},
        )
    except Exception:
        pass
