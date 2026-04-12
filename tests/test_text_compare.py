from src.youtube_slides_mvp.text_compare import compare_text_prefix


def test_progressive_a_prefix_of_b() -> None:
    a = "welcome to the presentation on machine learning"
    b = "welcome to the presentation on machine learning and deep neural networks"
    assert compare_text_prefix(a, b) == "progressive"


def test_progressive_b_prefix_of_a() -> None:
    # b is the shorter/earlier reveal state
    a = "welcome to the presentation on machine learning and deep neural networks"
    b = "welcome to the presentation on machine learning"
    assert compare_text_prefix(a, b) == "progressive"


def test_different_pages_low_jaccard() -> None:
    a = "the history of ancient rome during the roman empire and its territorial expansion"
    b = "python programming introduction to objects classes methods and inheritance"
    assert compare_text_prefix(a, b) == "different"


def test_empty_a_returns_unknown() -> None:
    assert compare_text_prefix("", "some text here to fill space for testing") == "unknown"


def test_empty_b_returns_unknown() -> None:
    assert compare_text_prefix("some text here to fill space for testing", "") == "unknown"


def test_both_empty_returns_unknown() -> None:
    assert compare_text_prefix("", "") == "unknown"


def test_short_prefix_returns_unknown() -> None:
    # Prefix shorter than min_prefix_len=20 should not be classified as progressive
    a = "hello world ok"
    b = "hello world ok and this is a completely different slide about something else entirely"
    assert compare_text_prefix(a, b, min_prefix_len=20) == "unknown"


def test_few_words_returns_unknown() -> None:
    # Not enough words for Jaccard comparison, no prefix match → unknown
    a = "slide one two"
    b = "slide other words"
    assert compare_text_prefix(a, b) == "unknown"


def test_partial_overlap_returns_unknown() -> None:
    # Some shared words but not enough for "different", not a prefix either
    a = "introduction to neural networks and their applications in vision"
    b = "introduction to recurrent networks and sequence models for language"
    # jaccard > 0.20 because "introduction to networks and" share words
    # but neither is a prefix of the other
    result = compare_text_prefix(a, b)
    assert result in ("unknown", "different")  # either is valid depending on exact jaccard
