"""Extract atomic, independently-checkable claims from the Writer's draft.

Convention: the Writer cites inline as it drafts, `... sentence text. [[src_id]]`
(comma-separated for multiple sources). A sentence with no citation marker
still becomes a Claim — with empty evidence — so it verifies to UNSUPPORTED
rather than silently disappearing. An uncited claim is exactly the failure
mode this system exists to catch, not one to hide by skipping extraction.

The marker is expected after the sentence's closing punctuation (see the
prompt in `nodes/writer.py`), but an LLM writer will sometimes place it
before its own period instead — `... sentence text [[src_id]].` — so
`_CITATION` also matches that form and folds the trailing punctuation back
onto the claim text rather than discarding it. Without this, every
LLM-drafted claim in a run gets zero evidence and the whole report comes
back 0% supported regardless of how good the underlying research was (see
`test_citation_before_trailing_punctuation`).
"""

from __future__ import annotations

import re

from ..state import Claim, EvidenceSpan, Source

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?!\[\[)|(?<=\]\])\s+")
_CITATION = re.compile(r"\[\[([^\]]+)\]\](?P<punct>[.!?])?\s*$")


def _candidate_evidence(source: Source) -> EvidenceSpan:
    return EvidenceSpan(
        source_id=source.id,
        char_start=0,
        char_end=len(source.raw_text),
        text=source.raw_text,
        locator="full-source (pre-verification candidate)",
    )


def extract_claims(
    draft_markdown: str,
    sources: dict[str, Source],
    sub_question_id: str = "",
) -> list[Claim]:
    claims: list[Claim] = []
    section = ""
    order = 0

    for raw_line in draft_markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            continue

        for sentence in _SENT_SPLIT.split(line):
            sentence = sentence.strip()
            if not sentence:
                continue

            match = _CITATION.search(sentence)
            cited_ids: list[str] = []
            text = sentence
            if match:
                cited_ids = [s.strip() for s in match.group(1).split(",") if s.strip()]
                text = sentence[: match.start()].strip() + (match.group("punct") or "")
            if not text:
                continue

            evidence = [
                _candidate_evidence(sources[sid]) for sid in cited_ids if sid in sources
            ]

            order += 1
            claims.append(
                Claim(
                    text=text,
                    section=section,
                    order=order,
                    sub_question_id=sub_question_id or None,
                    evidence=evidence,
                )
            )

    return claims
