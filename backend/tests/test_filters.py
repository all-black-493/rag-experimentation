from app.retrieval.filters import LegalFilters, build_filter, collections_in_scope, merge


def test_nothing_restricted_builds_no_filter():
    assert build_filter(LegalFilters(), "case_law") is None
    assert build_filter(LegalFilters(), "legislation") is None


def test_court_filter_applies_to_case_law_only():
    filters = LegalFilters(courts=("kesc",))

    assert build_filter(filters, "case_law") is not None
    # Legislation has no court; sending the clause would hit a property that
    # doesn't exist on that collection.
    assert build_filter(filters, "legislation") is None


def test_year_bounds_apply_to_both_collections():
    filters = LegalFilters(year_from=2024, year_to=2025)

    assert build_filter(filters, "case_law") is not None
    assert build_filter(filters, "legislation") is not None


def test_describe_omits_unset_fields():
    assert LegalFilters(courts=("kehc",), year_to=2025).describe() == {
        "courts": ["kehc"],
        "year_to": 2025,
    }
    assert LegalFilters().describe() == {}


def test_scope_defaults_to_every_collection():
    assert collections_in_scope(LegalFilters()) == ("legislation", "case_law")
    assert collections_in_scope(LegalFilters(collections=("case_law",))) == ("case_law",)


def test_merge_lets_the_planner_narrow_within_an_open_user_filter():
    merged = merge(LegalFilters(), LegalFilters(courts=("kesc",), year_from=2025))

    assert merged.courts == ("kesc",)
    assert merged.year_from == 2025


def test_merge_never_widens_the_users_court_choice():
    """A user who chose the Supreme Court must not see High Court results."""
    merged = merge(LegalFilters(courts=("kesc",)), LegalFilters(courts=("kehc", "kesc")))

    assert merged.courts == ("kesc",)


def test_merge_falls_back_to_the_user_when_courts_do_not_overlap():
    merged = merge(LegalFilters(courts=("kesc",)), LegalFilters(courts=("kemc",)))

    assert merged.courts == ("kesc",)


def test_merge_intersects_year_ranges():
    merged = merge(LegalFilters(year_from=2020, year_to=2026), LegalFilters(year_from=2024))

    assert (merged.year_from, merged.year_to) == (2024, 2026)


def test_merge_discards_an_impossible_planner_range():
    """User wants 2024–2025; planner says 2026+. The user's range stands."""
    merged = merge(LegalFilters(year_from=2024, year_to=2025), LegalFilters(year_from=2026))

    assert (merged.year_from, merged.year_to) == (2024, 2025)


def test_narrows_beyond_ignores_collection_choice():
    user = LegalFilters()
    assert not LegalFilters(collections=("case_law",)).narrows_beyond(user)
    assert LegalFilters(courts=("kesc",)).narrows_beyond(user)
    assert LegalFilters(year_to=2025).narrows_beyond(user)
