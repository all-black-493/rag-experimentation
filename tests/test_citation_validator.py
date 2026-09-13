from app.scoring import citation_coverage, strip_invalid_citations


def test_valid_markers_are_left_alone():
    answer = "The limit is $150 [1]. It renews monthly [2]."

    cleaned, stripped = strip_invalid_citations(answer, citation_count=2)

    assert cleaned == answer
    assert stripped == []


def test_marker_past_the_end_is_removed():
    """A [7] with 2 citations is a reference the reader can't check."""
    cleaned, stripped = strip_invalid_citations("Supported [1][7].", citation_count=2)

    assert cleaned == "Supported [1]."
    assert stripped == [7]


def test_the_claim_survives_even_when_its_only_marker_goes():
    """Dropping the sentence would be a worse trade than dropping the marker."""
    cleaned, stripped = strip_invalid_citations("Rates rose sharply [9].", citation_count=1)

    assert cleaned == "Rates rose sharply."
    assert stripped == [9]


def test_zero_is_invalid_since_citations_are_one_based():
    cleaned, stripped = strip_invalid_citations("Claim [0].", citation_count=3)

    assert stripped == [0]
    assert cleaned == "Claim."


def test_repeated_bad_marker_is_reported_once():
    _, stripped = strip_invalid_citations("A [5]. B [5].", citation_count=1)

    assert stripped == [5]


def test_declined_answer_with_no_citations_strips_everything():
    cleaned, stripped = strip_invalid_citations("I can't answer [1].", citation_count=0)

    assert cleaned == "I can't answer."
    assert stripped == [1]


def test_stripping_then_scoring_reports_no_invalid_markers():
    """After enforcement the served answer is self-consistent."""
    cleaned, _ = strip_invalid_citations("A [1]. B [9].", citation_count=1)

    assert citation_coverage(cleaned, 1).invalid_indices == []
