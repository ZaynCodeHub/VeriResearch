from veriresearch.verify.grounding import locate_quote


def test_exact_match():
    result = locate_quote("the cat sat", "before. the cat sat. after.")
    assert result.grounded
    assert result.method == "exact"
    assert result.char_start == 8


def test_normalised_match_smart_quotes_and_whitespace():
    source = "She said “the cat sat” over there."
    result = locate_quote("she said \"the   cat sat\"", source)
    assert result.grounded
    assert result.method == "normalised"


def test_fuzzy_match_above_floor():
    source = "The quick brown fox jumps over the lazy dog near the old barn."
    result = locate_quote("The quick brown fox jump over the lazy dog", source, fuzzy_floor=0.7)
    assert result.grounded
    assert result.method == "fuzzy"
    assert result.similarity >= 0.7


def test_no_match_returns_ungrounded():
    result = locate_quote("nothing like this exists here", "completely unrelated text")
    assert not result.grounded
    assert result.method == "none"


def test_empty_quote_is_ungrounded():
    result = locate_quote("", "some source text")
    assert not result.grounded


def test_confidence_multiplier_exact_is_full_trust():
    result = locate_quote("the cat sat", "before. the cat sat. after.")
    assert result.confidence_multiplier == 1.0


def test_confidence_multiplier_ungrounded_is_zero():
    result = locate_quote("not present anywhere", "totally different text")
    assert result.confidence_multiplier == 0.0
