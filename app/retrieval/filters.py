"""Metadata filters for retrieval.

Translated into Weaviate's own `Filter` objects and pushed down into the hybrid
query, so they are applied by the database *before* ranking rather than by
discarding results afterwards. Post-filtering is the tempting shortcut and it's
wrong: ask for 60 candidates and filter after, and a narrow filter leaves you
with three, silently degrading recall exactly when the user has been most
specific about what they want.

Filters are a query-time concern only. They never widen what a session can see -
tenancy already bounds that - they only narrow it.
"""

from dataclasses import dataclass, field

from weaviate.classes.query import Filter

from app.metadata import SourceType


@dataclass(frozen=True)
class RetrievalFilters:
    """What to restrict retrieval to. Every field is optional and ANDed."""

    source_types: list[SourceType] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)
    # Inclusive page bounds, only meaningful alongside a PDF source.
    page_from: int | None = None
    page_to: int | None = None

    def is_empty(self) -> bool:
        return not any(
            (self.source_types, self.sources, self.doc_ids, self.page_from, self.page_to)
        )

    def describe(self) -> dict:
        """Compact form for traces, so a filtered query is legible in Langfuse."""
        return {
            k: v
            for k, v in {
                "source_types": self.source_types,
                "sources": self.sources,
                "doc_ids": self.doc_ids,
                "page_from": self.page_from,
                "page_to": self.page_to,
            }.items()
            if v
        }


def build_filter(filters: RetrievalFilters) -> Filter | None:
    """Compose a Weaviate filter, or None when nothing is restricted."""
    if filters.is_empty():
        return None

    clauses = []
    if filters.source_types:
        clauses.append(Filter.by_property("source_type").contains_any(filters.source_types))
    if filters.sources:
        clauses.append(Filter.by_property("source").contains_any(filters.sources))
    if filters.doc_ids:
        clauses.append(Filter.by_property("doc_id").contains_any(filters.doc_ids))
    if filters.page_from is not None:
        clauses.append(Filter.by_property("page").greater_or_equal(filters.page_from))
    if filters.page_to is not None:
        clauses.append(Filter.by_property("page").less_or_equal(filters.page_to))

    # Filter.all_of on a single clause is valid but noisier in the query log.
    return clauses[0] if len(clauses) == 1 else Filter.all_of(clauses)
