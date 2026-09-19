"""Metadata restrictions on retrieval, pushed down into the Weaviate query.

Applied by the database *before* ranking rather than by discarding results
after. Post-filtering is the tempting shortcut and it's wrong: ask for 60
candidates and filter after, and a narrow filter leaves you with three, silently
degrading recall exactly when the user has been most specific.

Two sources of filters meet here. The user's, from the UI, are hard constraints.
The planner's, inferred from the question, are suggestions that narrow within
them and can be relaxed when they turn out too narrow. `merge` encodes that
precedence; nothing downstream needs to know which was which.
"""

from dataclasses import dataclass

from weaviate.classes.query import Filter

from app.metadata import COLLECTIONS, Collection


@dataclass(frozen=True)
class LegalFilters:
    """What to restrict retrieval to. Every field optional; all ANDed."""

    collections: tuple[Collection, ...] = ()
    # Court codes (see app.corpus.courts). Only meaningful for case law.
    courts: tuple[str, ...] = ()
    # Inclusive. Year decided for judgments, year enacted for Acts.
    year_from: int | None = None
    year_to: int | None = None

    def is_empty(self) -> bool:
        return not (self.collections or self.courts or self.year_from or self.year_to)

    def allows(self, collection: Collection) -> bool:
        return not self.collections or collection in self.collections

    def admits(self, metadata: dict) -> bool:
        """Whether one already-fetched passage falls within these restrictions.

        The graph hands retrieval specific passages by address; they never went
        through a filtered query, so the user's restrictions are checked here.
        """
        collection = metadata.get("collection")
        if not self.allows(collection):
            return False
        if collection == "case_law" and self.courts and metadata.get("court_code") not in self.courts:
            return False
        year = metadata.get("year")
        if (self.year_from is not None or self.year_to is not None) and year is None:
            return False
        return (self.year_from is None or year >= self.year_from) and (
            self.year_to is None or year <= self.year_to
        )

    def narrows_beyond(self, other: "LegalFilters") -> bool:
        """Whether this restricts courts or years more than `other` does.

        Collection choice is excluded: it decides *where* a sub-query runs, not
        how many results it can find there.
        """
        return (
            self.courts != other.courts
            or self.year_from != other.year_from
            or self.year_to != other.year_to
        )

    def narrowing(self) -> dict:
        """Just the court and year restrictions - what a sub-query adds beyond its collection."""
        return {k: v for k, v in self.describe().items() if k != "collections"}

    def describe(self) -> dict:
        """Compact form for traces and the API, omitting what isn't set."""
        return {
            key: value
            for key, value in {
                "collections": list(self.collections),
                "courts": list(self.courts),
                "year_from": self.year_from,
                "year_to": self.year_to,
            }.items()
            if value
        }


def merge(user: LegalFilters, planned: LegalFilters) -> LegalFilters:
    """The planner's filters, bounded by the user's.

    A user who chose "Supreme Court" must never see High Court results because the
    planner thought they'd help; a user who chose nothing gets whatever the
    planner inferred. Where both restrict the same field the result is the
    intersection - and an empty intersection falls back to the user's choice,
    since the planner's guess is the less trustworthy of the two.
    """
    if user.courts and planned.courts:
        courts = tuple(c for c in planned.courts if c in user.courts) or user.courts
    else:
        courts = user.courts or planned.courts

    year_from = max(filter(None, (user.year_from, planned.year_from)), default=None)
    year_to = min(filter(None, (user.year_to, planned.year_to)), default=None)
    if year_from and year_to and year_from > year_to:
        year_from, year_to = user.year_from, user.year_to

    return LegalFilters(
        collections=user.collections or planned.collections,
        courts=courts,
        year_from=year_from,
        year_to=year_to,
    )


def build_filter(filters: LegalFilters, collection: Collection) -> Filter | None:
    """The Weaviate filter for one collection, or None when nothing applies.

    Per collection because the properties differ: a court filter means nothing
    to legislation and is dropped there rather than sent to a property that
    doesn't exist.
    """
    clauses = []
    if collection == "case_law" and filters.courts:
        clauses.append(Filter.by_property("court_code").contains_any(list(filters.courts)))
    if filters.year_from is not None:
        clauses.append(Filter.by_property("year").greater_or_equal(filters.year_from))
    if filters.year_to is not None:
        clauses.append(Filter.by_property("year").less_or_equal(filters.year_to))

    if not clauses:
        return None
    # Filter.all_of on a single clause is valid but noisier in the query log.
    return clauses[0] if len(clauses) == 1 else Filter.all_of(clauses)


def collections_in_scope(filters: LegalFilters) -> tuple[Collection, ...]:
    return filters.collections or COLLECTIONS
