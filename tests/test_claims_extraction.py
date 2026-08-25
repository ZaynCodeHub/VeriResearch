from veriresearch.state import Source
from veriresearch.verify.claims import extract_claims

SOURCE = Source(id="src_a", url="https://example.com/a", raw_text="Example raw text.")


def test_cited_sentence_gets_evidence():
    draft = "## Section\n\nThe sky is blue. [[src_a]]\n"
    claims = extract_claims(draft, {SOURCE.id: SOURCE})
    assert len(claims) == 1
    assert claims[0].text == "The sky is blue."
    assert claims[0].source_ids == ["src_a"]


def test_uncited_sentence_still_extracted_with_no_evidence():
    draft = "## Section\n\nThe sky is blue.\n"
    claims = extract_claims(draft, {SOURCE.id: SOURCE})
    assert len(claims) == 1
    assert claims[0].source_ids == []


def test_multi_source_citation_marker():
    other = Source(id="src_b", url="https://example.com/b", raw_text="Other text.")
    draft = "## Section\n\nA fact from two places. [[src_a,src_b]]\n"
    claims = extract_claims(draft, {SOURCE.id: SOURCE, other.id: other})
    assert set(claims[0].source_ids) == {"src_a", "src_b"}


def test_heading_sets_claim_section():
    draft = "## My Heading\n\nSome fact. [[src_a]]\n"
    claims = extract_claims(draft, {SOURCE.id: SOURCE})
    assert claims[0].section == "My Heading"


def test_citation_marker_survives_sentence_splitting():
    """Regression: the sentence-split regex must not orphan the trailing
    citation marker into its own empty 'sentence' (see claims.py's negative
    lookahead)."""
    draft = "## Section\n\nFirst fact here. [[src_a]] Second fact here. [[src_a]]\n"
    claims = extract_claims(draft, {SOURCE.id: SOURCE})
    assert len(claims) == 2
    assert all(c.source_ids == ["src_a"] for c in claims)


def test_citation_before_trailing_punctuation():
    """Regression: the real LLM writer places the marker before the sentence's
    own closing punctuation ("... text [[src_id]].") rather than after it
    ("... text. [[src_id]]"). Before this fix, `_CITATION`'s end-of-string
    anchor missed this form entirely, so every LLM-drafted claim got zero
    evidence and the run came back 0% supported regardless of the research."""
    draft = "## Section\n\nThe tower is 330 meters tall [[src_a]].\n"
    claims = extract_claims(draft, {SOURCE.id: SOURCE})
    assert len(claims) == 1
    assert claims[0].text == "The tower is 330 meters tall."
    assert claims[0].source_ids == ["src_a"]
