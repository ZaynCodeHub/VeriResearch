"""Anchor a judge's quoted justification back into the source document.

The problem
-----------
An LLM judge that returns `{"label": "SUPPORTED", "quote": "..."}` can fabricate
the quote. If we take the label at face value, a hallucinated justification
becomes a green checkmark in the report — the exact failure the whole system
exists to prevent.

The fix
-------
Every quote is located in the source's raw text. Three matching tiers:

  1. exact substring match
  2. whitespace/quote/dash-normalised match (models silently reflow whitespace
     and swap smart quotes; that is not fabrication)
  3. fuzzy match above a similarity floor, which recovers minor drift while
     still refusing wholesale invention

Tier 1 and 2 are `grounded=True`. Tier 3 is grounded but records the similarity
so the confidence calibration can discount it. No match at all is
`grounded=False`, and the verifier multiplies that judgment's confidence by
`ungrounded_penalty`.

Returning offsets (not just a boolean) is what makes the frontend's "click a
claim to see the checked text" feature a highlight-range lookup.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from ..state import EvidenceSpan, Source

_WS_RE = re.compile(r"\s+")
_SMART_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u2010": "-", "\u2011": "-",
    "\u00a0": " ", "\u2026": "...",
}


@dataclass
class GroundingResult:
    grounded: bool
    char_start: int = -1
    char_end: int = -1
    matched_text: str = ""
    similarity: float = 0.0
    method: str = "none"    # exact | normalised | fuzzy | none

    @property
    def confidence_multiplier(self) -> float:
        """How much to trust a judgment carrying this quote."""
        if not self.grounded:
            return 0.0                      # caller applies its own penalty
        if self.method in ("exact", "normalised"):
            return 1.0
        return 0.75 + 0.25 * self.similarity


def _canonicalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for src, dst in _SMART_MAP.items():
        text = text.replace(src, dst)
    return text


def _normalise(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace, lowercase, and return an index map to the original.

    `index_map[i]` is the offset in the *canonicalised* string of the i-th
    character of the normalised string, so a match found in normalised space can
    be translated back to real character offsets.
    """
    canon = _canonicalise(text)
    out_chars: list[str] = []
    index_map: list[int] = []
    prev_space = True
    for i, ch in enumerate(canon):
        if ch.isspace():
            if prev_space:
                continue
            out_chars.append(" ")
            index_map.append(i)
            prev_space = True
        else:
            out_chars.append(ch.lower())
            index_map.append(i)
            prev_space = False
    while out_chars and out_chars[-1] == " ":
        out_chars.pop()
        index_map.pop()
    return "".join(out_chars), index_map


def _fuzzy_locate(needle: str, haystack: str, floor: float) -> tuple[int, int, float]:
    """Best-matching window of `haystack` for `needle`, by SequenceMatcher ratio."""
    n = len(needle)
    if n == 0 or len(haystack) < n // 2:
        return -1, -1, 0.0

    best_ratio, best_start, best_end = 0.0, -1, -1
    # Slide a window of roughly the needle's length; step scales with size so
    # long quotes don't turn this into an O(n*m) crawl.
    step = max(1, n // 8)
    for size in (n, int(n * 1.25) + 1):
        for start in range(0, max(1, len(haystack) - size + 1), step):
            window = haystack[start : start + size]
            ratio = SequenceMatcher(None, needle, window, autojunk=False).ratio()
            if ratio > best_ratio:
                best_ratio, best_start, best_end = ratio, start, start + len(window)

    if best_ratio < floor:
        return -1, -1, best_ratio
    return best_start, best_end, best_ratio


def locate_quote(quote: str, source_text: str, fuzzy_floor: float = 0.82) -> GroundingResult:
    """Find `quote` inside `source_text` and report how confidently."""
    if not quote or not quote.strip():
        return GroundingResult(grounded=False, method="none")

    # Tier 1 — exact.
    idx = source_text.find(quote)
    if idx != -1:
        return GroundingResult(
            grounded=True, char_start=idx, char_end=idx + len(quote),
            matched_text=quote, similarity=1.0, method="exact",
        )

    # Tier 2 — normalised.
    norm_src, src_map = _normalise(source_text)
    norm_quote, _ = _normalise(quote)
    if not norm_quote:
        return GroundingResult(grounded=False, method="none")

    idx = norm_src.find(norm_quote)
    if idx != -1:
        start = src_map[idx]
        end = src_map[min(idx + len(norm_quote) - 1, len(src_map) - 1)] + 1
        return GroundingResult(
            grounded=True, char_start=start, char_end=end,
            matched_text=source_text[start:end], similarity=1.0, method="normalised",
        )

    # Tier 3 — fuzzy.
    f_start, f_end, ratio = _fuzzy_locate(norm_quote, norm_src, fuzzy_floor)
    if f_start != -1:
        start = src_map[f_start]
        end = src_map[min(f_end - 1, len(src_map) - 1)] + 1
        return GroundingResult(
            grounded=True, char_start=start, char_end=end,
            matched_text=source_text[start:end], similarity=ratio, method="fuzzy",
        )

    return GroundingResult(grounded=False, similarity=ratio, method="none")


def ground_quote_in_source(quote: str, source: Source, locator: str = "") -> tuple[GroundingResult, Optional[EvidenceSpan]]:
    """Ground a quote and, on success, return a citable EvidenceSpan."""
    result = locate_quote(quote, source.raw_text)
    if not result.grounded:
        return result, None
    span = EvidenceSpan(
        source_id=source.id,
        char_start=result.char_start,
        char_end=result.char_end,
        text=result.matched_text,
        locator=locator or f"chars {result.char_start}-{result.char_end}",
    )
    return result, span
