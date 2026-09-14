from app.retrieval.filters import RetrievalFilters, build_filter


def test_no_restrictions_produces_no_filter():
    """An unfiltered query must not carry an empty filter into Weaviate."""
    assert build_filter(RetrievalFilters()) is None
    assert RetrievalFilters().is_empty()


def test_single_restriction_builds_a_filter():
    assert build_filter(RetrievalFilters(source_types=["pdf"])) is not None


def test_restrictions_combine():
    filters = RetrievalFilters(source_types=["pdf"], sources=["a.pdf"], page_from=2)

    assert not filters.is_empty()
    assert build_filter(filters) is not None


def test_page_bounds_alone_are_a_restriction():
    assert not RetrievalFilters(page_to=5).is_empty()
    assert build_filter(RetrievalFilters(page_to=5)) is not None


def test_describe_omits_unset_fields():
    """Traces should show what was restricted, not a wall of nulls."""
    described = RetrievalFilters(sources=["a.pdf"], page_from=3).describe()

    assert described == {"sources": ["a.pdf"], "page_from": 3}


def test_describe_is_empty_when_nothing_is_restricted():
    assert RetrievalFilters().describe() == {}
