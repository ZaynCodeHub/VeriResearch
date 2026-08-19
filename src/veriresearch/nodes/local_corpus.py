"""A tiny bundled corpus of hand-written, fact-checked passages.

The honest offline researcher fallback (`researcher.py`'s `_offline_placeholder`)
deliberately contains no factual claims, so a fully-offline run of an arbitrary
topic produces a degenerate 0/0 comparison — there is nothing to verify. That's
correct behaviour for arbitrary topics (we will not invent facts to fill the
gap), but it makes the before/after demo uninteresting without API keys.

This module trades breadth for accuracy: a handful of topics the maintainer
can vouch for personally (well-established, stable, textbook-level facts, kept
conservative), each written with one deliberate contrast/nuance sentence so
CONTRADICTED-type claims have something real to be checked against. The
golden topic set (`eval/golden_topics.py`) is weighted toward these so
`scripts/compare_before_after.py` produces a meaningful chart with zero API
keys. Anything outside this corpus still falls back to the honest empty
placeholder — this is a demo convenience, not a general-purpose offline
search engine.
"""

from __future__ import annotations

import re
from typing import Optional

from ..state import Source

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "is",
    "are", "was", "were", "what", "how", "who", "does", "do", "did", "its",
}


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


_CORPUS: list[Source] = [
    Source(
        id="corpus_jwst",
        url="local-corpus://james-webb-space-telescope",
        title="James Webb Space Telescope",
        raw_text=(
            "The James Webb Space Telescope (JWST) launched on December 25, 2021, from "
            "Europe's Spaceport near Kourou, French Guiana, atop an Ariane 5 rocket. "
            "It is the largest and most powerful space telescope ever built. "
            "Its primary mirror is 6.5 meters in diameter, made of 18 hexagonal "
            "gold-coated beryllium segments. "
            "JWST observes primarily in the infrared, which lets it see through dust "
            "clouds and detect the faint light of the earliest galaxies. "
            "Unlike Hubble, which orbits Earth at low altitude, JWST does not orbit "
            "Earth; instead it orbits the Sun near the second Lagrange point (L2), "
            "about 1.5 million kilometers away. "
            "The telescope is a collaboration between NASA, the European Space Agency, "
            "and the Canadian Space Agency. "
            "Its first full-colour science images were released on July 12, 2022."
        ),
    ),
    Source(
        id="corpus_great_wall",
        url="local-corpus://great-wall-of-china",
        title="The Great Wall of China",
        raw_text=(
            "The Great Wall of China is a series of fortifications built across the "
            "historical northern borders of China to protect against raids and invasions. "
            "Construction began more than two thousand years ago, with major sections "
            "built or rebuilt during the Qin, Han, and Ming dynasties. "
            "Contrary to a popular claim, the Great Wall is not visible to the naked eye "
            "from the Moon; that claim has been debunked by astronauts and is considered "
            "a myth. "
            "The wall is not a single continuous structure but a network of walls, "
            "trenches, and natural barriers spanning thousands of kilometers. "
            "Much of the wall visible to tourists today, including the sections near "
            "Beijing, was built or renovated during the Ming dynasty. "
            "UNESCO designated the Great Wall a World Heritage Site in 1987."
        ),
    ),
    Source(
        id="corpus_marie_curie",
        url="local-corpus://marie-curie",
        title="Marie Curie",
        raw_text=(
            "Marie Curie was a physicist and chemist who conducted pioneering research "
            "on radioactivity, a term she helped coin. "
            "She was the first woman to win a Nobel Prize, and remains the only person "
            "to win Nobel Prizes in two different sciences, physics and chemistry. "
            "Marie Curie did not work alone for most of her career; she collaborated "
            "closely with her husband Pierre Curie until his death in 1906, after which "
            "she continued their research and took over his teaching position at the "
            "University of Paris. "
            "She discovered the elements polonium and radium, both of which she named "
            "herself. "
            "Curie died in 1934 from aplastic anemia, a condition linked to her "
            "long-term exposure to radiation during research conducted without the "
            "safety precautions used today."
        ),
    ),
    Source(
        id="corpus_wright_brothers",
        url="local-corpus://wright-brothers-first-flight",
        title="The Wright Brothers' First Flight",
        raw_text=(
            "Orville and Wilbur Wright are credited with designing, building, and flying "
            "the first successful motor-operated airplane. "
            "Their first powered, controlled flight took place on December 17, 1903, "
            "near Kitty Hawk, North Carolina. "
            "The brothers were not the first people to attempt powered flight, but "
            "earlier attempts by others had failed to achieve sustained, controlled "
            "flight. "
            "Contrary to a common assumption, their first flight was brief, covering "
            "about 120 feet and lasting roughly 12 seconds, far shorter than later "
            "flights that same day. "
            "The Wright brothers ran a bicycle shop in Dayton, Ohio, before turning "
            "their engineering skills toward aviation. "
            "Their work built on aerodynamic research conducted by earlier pioneers, "
            "including Otto Lilienthal."
        ),
    ),
    Source(
        id="corpus_great_barrier_reef",
        url="local-corpus://great-barrier-reef",
        title="The Great Barrier Reef",
        raw_text=(
            "The Great Barrier Reef is the world's largest coral reef system, located "
            "off the coast of Queensland, Australia. "
            "It is composed of thousands of individual reefs and hundreds of islands, "
            "stretching over more than 2,000 kilometers. "
            "The reef is not a single organism but a vast ecosystem built up over "
            "thousands of years by billions of tiny coral polyps. "
            "Rising ocean temperatures have caused repeated mass coral bleaching events "
            "on the reef in recent decades; bleaching is not a sign of healthy coral but "
            "a stress response that can lead to coral death if conditions do not "
            "improve. "
            "The Great Barrier Reef was designated a UNESCO World Heritage Site in 1981. "
            "It is large enough to be seen from space, unlike some other well-known "
            "structures that are commonly but incorrectly said to be visible from orbit."
        ),
    ),
    Source(
        id="corpus_honeybee_dance",
        url="local-corpus://honeybee-waggle-dance",
        title="The Honeybee Waggle Dance",
        raw_text=(
            "Honeybees communicate the location of food sources to other members of "
            "their colony through a behavior known as the waggle dance. "
            "The dance was first systematically described by the Austrian ethologist "
            "Karl von Frisch, who won a Nobel Prize in 1973 for his research on animal "
            "communication. "
            "During the waggle dance, a foraging bee moves in a figure-eight pattern, "
            "with the angle of the waggle run relative to vertical indicating the "
            "direction of the food source relative to the sun. "
            "The dance does not directly show the exact coordinates of the food "
            "source; rather, it conveys direction and approximate distance, which other "
            "bees interpret before locating the source themselves. "
            "Longer waggle runs generally indicate that a food source is farther away "
            "from the hive. "
            "The waggle dance is performed inside the dark hive, so nearby bees sense "
            "the dance primarily through vibration and touch rather than sight."
        ),
    ),
]

_MATCH_FLOOR = 0.34


def match_corpus(topic: str) -> Optional[Source]:
    """Best corpus entry for `topic` by keyword overlap, or None below the floor."""
    topic_kw = _keywords(topic)
    if not topic_kw:
        return None

    best_entry, best_score = None, 0.0
    for entry in _CORPUS:
        entry_kw = _keywords(entry.title)
        score = len(topic_kw & entry_kw) / max(1, len(topic_kw))
        if score > best_score:
            best_score, best_entry = score, entry

    return best_entry if best_score >= _MATCH_FLOOR else None
