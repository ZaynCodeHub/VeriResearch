"""The golden topic set for `scripts/compare_before_after.py` and the Ragas harness.

**Placeholder.** These 18 topics were drafted by the maintainer to unblock
building and testing the eval harness before a real curated set was ready —
swap `GOLDEN_TOPICS` for your own 15-20 topics and every downstream script
(before/after comparison, Ragas report) picks them up with no code changes.

The first six deliberately match entries in `nodes/local_corpus.py`, so the
before/after comparison produces a real, non-degenerate signal even with zero
API keys (see that module's docstring for why). The rest span a few unrelated
domains on purpose — tech, economics, health, history — so the demo doesn't
read as monotone; with `TAVILY_API_KEY`/`GROK_API_KEY` set, all 18 run
against live search and a live LLM writer/judge instead of the offline path.
"""

from __future__ import annotations

GOLDEN_TOPICS: list[str] = [
    # --- matches the bundled local corpus (meaningful offline signal) ---
    "the James Webb Space Telescope",
    "the Great Wall of China",
    "Marie Curie's scientific legacy",
    "the Wright brothers' first flight",
    "the Great Barrier Reef",
    "how honeybees communicate via the waggle dance",
    # --- generic topics (degenerate offline; meaningful with live keys) ---
    "quantum computing error correction",
    "the economics of carbon capture technology",
    "CRISPR gene editing ethics",
    "the history of the printing press",
    "renewable energy grid storage solutions",
    "the rise of remote work after the COVID-19 pandemic",
    "artificial intelligence regulation in the European Union",
    "the causes of the 2008 financial crisis",
    "vaccine development timelines",
    "the impact of social media on mental health",
    "electric vehicle battery recycling",
    "the future of nuclear fusion energy",
]
