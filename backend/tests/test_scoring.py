from app.scoring import citation_coverage


def test_fully_cited_answer_scores_one():
    report = citation_coverage("The limit is $150 [1]. It renews monthly [2].", citation_count=2)

    assert report.coverage == 1.0
    assert report.cited_sentences == 2
    assert report.cited_indices == [1, 2]
    assert report.unused_citations == []


def test_uncited_sentences_lower_coverage():
    answer = "The limit is $150 [1]. It probably renews monthly."

    report = citation_coverage(answer, citation_count=1)

    assert report.coverage == 0.5
    assert report.cited_sentences == 1
    assert report.sentences == 2


def test_flags_markers_pointing_past_the_citation_list():
    """A [4] when only 2 citations came back is an invented reference."""
    report = citation_coverage("Supported [1]. Also supported [4].", citation_count=2)

    assert report.invalid_indices == [4]
    assert report.cited_indices == [1]
    # It still counts as a cited sentence - which is exactly why the invalid
    # count is tracked separately rather than folded into coverage.
    assert report.coverage == 1.0


def test_reports_citations_the_answer_never_used():
    report = citation_coverage("Only the first matters [1].", citation_count=3)

    assert report.unused_citations == [2, 3]


def test_markdown_bullets_count_as_sentences():
    answer = "- First point [1]\n- Second point\n- Third point [2]"

    report = citation_coverage(answer, citation_count=2)

    assert report.sentences == 3
    assert report.cited_sentences == 2


def test_empty_answer_scores_zero_rather_than_dividing_by_zero():
    report = citation_coverage("", citation_count=0)

    assert report.coverage == 0.0
    assert report.sentences == 0


def test_decline_message_has_no_coverage():
    """A decline cites nothing by design, so it must not look fully covered."""
    report = citation_coverage("I don't have enough information to answer that.", 0)

    assert report.coverage == 0.0
