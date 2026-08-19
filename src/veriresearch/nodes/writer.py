"""Writer node: sources -> cited draft markdown -> extracted Claims.

Every sentence the writer states as fact is required (by prompt, when an LLM
is drafting) or by construction (in the deterministic fallback, which only
ever emits sentences copied verbatim from a source) to carry a `[[source_id]]`
citation marker. `verify.claims.extract_claims` then turns that markdown into
`Claim` objects the Verifier can check — a claim with no marker still gets
extracted, just with empty evidence, so an uncited sentence is caught as
UNSUPPORTED rather than silently dropped before verification ever sees it.

The claim dict is returned wrapped in `state.Replace`: the writer produces a
fresh claim set on every pass (including after a revision loop), and the
default dict-merge reducer would leave the previous pass's claims in state,
double-counting them in the supported-rate. See `state.py`'s `Replace` note.

Demo-only note on the deterministic path: because it only ever copies real
sentences verbatim, every claim it drafts would trivially self-verify as
SUPPORTED (a sentence checked against the document it was copied from always
matches) — which would make the offline before/after demo look artificially
perfect and never exercise the verifier at all. `_deterministic_draft`
therefore perturbs a fixed fraction of sentences by one of two deterministic
means: (1) stripping a negation ("does not orbit Earth" -> "orbits Earth"),
which is real text still cited to its real (and still-negating) source, so
the verifier correctly calls it CONTRADICTED; or (2), when a sentence has no
negation to strip, mis-citing it to a different source than the one it came
from. Both are real, well-documented automated-writer failure modes (dropped
qualifiers; wrong-document attribution) — neither invents a fact that isn't
verbatim in some real source. This only fires in the no-LLM fallback and is
disabled the moment `GROK_API_KEY` is set.

Revision feedback: on a re-draft after `revise_node`, `writer_node` is handed
`revision_feedback` — the exact text, label, and rationale of every claim the
verifier just rejected (see `nodes/verifier_node.py::_build_revision_feedback`).
The LLM path folds this into the prompt as a "these were rejected, fix or
drop them" instruction. The deterministic path can't reason about rationale,
but it can at least stop reproducing the identical rejected sentence: it
avoids re-emitting a negated or mis-cited sentence whose exact text was
flagged last pass, falling through to the next candidate (another negatable
sentence in the same source, or a correct citation) instead.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

from ..config import SETTINGS
from ..state import RunState, Replace, Source, SubQuestion
from ..verify.claims import extract_claims

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _first_sentences(text: str, n: int) -> list[str]:
    sentences = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    return sentences[:n]


_DRIFT_EVERY_NTH = 3  # every 3rd sentence gets perturbed — see module docstring
_NEGATIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bis not\b", re.I), "is"),
    (re.compile(r"\bare not\b", re.I), "are"),
    (re.compile(r"\bdoes not\b", re.I), "does"),
    (re.compile(r"\bdid not\b", re.I), "did"),
    (re.compile(r"\bwas not\b", re.I), "was"),
    (re.compile(r"\bwere not\b", re.I), "were"),
    (re.compile(r"\bnot a\b", re.I), "a"),
]


def _strip_negation(sentence: str) -> Optional[str]:
    for pattern, replacement in _NEGATIONS:
        if pattern.search(sentence):
            return pattern.sub(replacement, sentence, count=1)
    return None


def _deterministic_draft(
    sub_questions: list[SubQuestion],
    sources: dict[str, Source],
    avoid_texts: frozenset[str] = frozenset(),
) -> str:
    lines: list[str] = []
    all_source_ids = list(sources.keys())
    sentence_index = 0

    for sq in sub_questions:
        lines.append(f"## {sq.text}\n")
        # The "no search backend configured" placeholder (researcher.py) is boilerplate
        # about the system, not research content — drafting claims from it would let a
        # claim trivially self-verify as SUPPORTED against text that isn't actually about
        # the topic. Treat it the same as "nothing retrieved" rather than draft from it.
        sq_sources = [
            s for s in sources.values()
            if s.retrieved_by == sq.id and s.url != "offline://no-search-backend"
        ]
        if not sq_sources:
            lines.append("No sources were retrieved for this sub-question.\n")
            continue
        for source in sq_sources:
            negated_this_source = False
            for sentence in _first_sentences(source.raw_text, n=6):
                cite_id = source.id
                text = sentence

                if not negated_this_source:
                    # Negate the first negatable sentence in each source, deterministically
                    # (not on a fixed modulo of the global sentence count — most corpus
                    # passages are 6 sentences and a %3 stride hits the same two positions
                    # every time, which can systematically miss the one negation sentence).
                    # If that exact negation was rejected last revision pass, skip it and
                    # keep looking for a *different* negatable sentence in this source
                    # instead of reproducing the same rejected claim verbatim.
                    negated = _strip_negation(sentence)
                    if negated and negated not in avoid_texts:
                        text = negated
                        negated_this_source = True
                elif sentence_index % _DRIFT_EVERY_NTH == _DRIFT_EVERY_NTH - 1:
                    # Same healing idea for the mis-citation perturbation: if this exact
                    # sentence was already flagged (mis-cited last pass), cite it correctly
                    # this time instead of mis-citing it again.
                    if sentence not in avoid_texts:
                        other_ids = [sid for sid in all_source_ids if sid != source.id]
                        if other_ids:
                            cite_id = other_ids[sentence_index % len(other_ids)]

                lines.append(f"{text} [[{cite_id}]]")
                sentence_index += 1
        lines.append("")
    return "\n".join(lines)


def _llm_draft(
    topic: str,
    sub_questions: list[SubQuestion],
    sources: dict[str, Source],
    revision_feedback: Optional[list[dict[str, Any]]] = None,
) -> Optional[str]:
    from ..llm import GrokClient

    system = (
        "You are a careful research writer. Using ONLY the provided source excerpts, write "
        "a markdown report with one '## <sub-question>' heading per sub-question below it. "
        "Every sentence that states a fact MUST end with an inline citation marker in the "
        "form [[source_id]] (comma-separate multiple ids: [[src_a,src_b]]), copied exactly "
        "from the source ids given. Do not state anything not present in the excerpts. If a "
        "sub-question has no sources, write one sentence saying so, with no citation marker."
    )

    blocks = [f"TOPIC: {topic}\n"]
    for sq in sub_questions:
        blocks.append(f"SUB-QUESTION: {sq.text} (id: {sq.id})")
        sq_sources = [s for s in sources.values() if s.retrieved_by == sq.id]
        if not sq_sources:
            blocks.append("  (no sources retrieved)")
            continue
        for source in sq_sources:
            excerpt = source.raw_text[:1500]
            blocks.append(f"  SOURCE [{source.id}] {source.url}\n  {excerpt}")

    if revision_feedback:
        # The verifier's specific objection, not just "try again": each entry is a claim
        # that was independently checked and rejected last pass, with the label and
        # rationale the judge gave. Fed back verbatim so the re-draft can fix the actual
        # problem (wrong source, unsupported figure, ...) instead of blindly rephrasing.
        fb_lines = [
            "REVISION NOTE: the claims below were independently verified against their "
            "cited sources and rejected. For each one, either rewrite it so it is "
            "accurately supported by one of the source excerpts above (citing the correct "
            "source id), or omit it entirely. Do not repeat any of them unchanged."
        ]
        for fb in revision_feedback:
            cites = ", ".join(fb.get("source_ids") or []) or "no source"
            fb_lines.append(
                f'  - "{fb["text"]}" — verdict {fb["label"]} (cited to {cites}): {fb["rationale"]}'
            )
        blocks.append("\n".join(fb_lines))

    prompt = "\n\n".join(blocks)

    try:
        client = GrokClient(model=SETTINGS.verifier.llm_model)
        response = client.complete(system, prompt, max_tokens=2000)
        return response.text
    except Exception:
        return None


def writer_node(state: RunState) -> dict[str, Any]:
    t0 = time.perf_counter()
    topic = state.get("topic", "")
    sub_questions = state.get("sub_questions", [])
    sources = state.get("sources", {})
    revision_feedback = state.get("revision_feedback") or []

    draft = (
        _llm_draft(topic, sub_questions, sources, revision_feedback=revision_feedback)
        if SETTINGS.planner.has_llm
        else None
    )
    drafted_by = "llm"
    if not draft or not draft.strip():
        avoid_texts = frozenset(fb["text"] for fb in revision_feedback)
        draft = _deterministic_draft(sub_questions, sources, avoid_texts=avoid_texts)
        drafted_by = "deterministic"

    claims = extract_claims(draft, sources)
    claims_by_id = {claim.id: claim for claim in claims}

    return {
        "draft_markdown": draft,
        "claims": Replace(claims_by_id),
        "trace": [
            {
                "node": "writer",
                "drafted_by": drafted_by,
                "claims_drafted": len(claims),
                "revision_feedback_applied": len(revision_feedback),
                "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        ],
    }
