"""Hermetic: the harness must never require `ragas` to be importable, or a
network call, unless GROK_API_KEY is actually set (it isn't in CI/tests)."""

from veriresearch.eval.ragas_harness import run_ragas_eval


def test_skips_cleanly_without_grok_key():
    result = run_ragas_eval(["a test topic"])
    assert result["status"] == "skipped"
    assert "GROK_API_KEY" in result["reason"]
