"""What the corpus contains, described once for the planner, the API and the UI.

The reference architecture's agent starts by inspecting the schema and
collections before deciding where to search. This is that inspection: which
collections exist, what each is for, how many documents they hold, which courts
and years are present. Built from the live database rather than written by hand,
so the planner is never told about a court the corpus doesn't have, and the UI's
filter rail never offers one.

Held by a `CatalogHolder` that rebuilds it after a TTL, so an ingest that ran in
another process shows up without a restart. The rebuild is a handful of
aggregate queries - cheap enough to do every few minutes, too slow for every
request.
"""

import threading
import time

from pydantic import BaseModel
from weaviate.classes.aggregate import GroupByAggregate, Metrics
from weaviate.classes.query import Filter
from weaviate.client import WeaviateClient

from app.corpus.courts import COURTS, court_name
from app.metadata import CLASS_NAMES, COLLECTIONS, LABELS, Collection

# What each collection is *for*, in the planner's terms. The one piece of the
# catalog that is authored rather than measured.
DESCRIPTIONS: dict[Collection, str] = {
    "legislation": (
        "Acts of the Kenyan Parliament and subsidiary legislation, as consolidated by "
        "Kenya Law. Use for what the law says: definitions, offences, penalties, "
        "procedures, powers and duties. Filterable by year enacted."
    ),
    "case_law": (
        "Judgments and rulings of Kenyan courts. Use for how courts have applied the "
        "law: holdings, sentences imposed, interpretations, precedent. Filterable by "
        "court and year decided."
    ),
}


class CourtInfo(BaseModel):
    code: str
    name: str
    rank: int
    documents: int


class CollectionInfo(BaseModel):
    key: Collection
    label: str
    description: str
    documents: int
    passages: int
    year_min: int | None = None
    year_max: int | None = None
    courts: list[CourtInfo] = []


class Catalog(BaseModel):
    collections: list[CollectionInfo]

    def get(self, key: Collection) -> CollectionInfo:
        return next(c for c in self.collections if c.key == key)

    def court_codes(self) -> set[str]:
        return {court.code for info in self.collections for court in info.courts}

    def for_planner(self) -> str:
        """The catalog as prose the planner can reason over."""
        lines = []
        for info in self.collections:
            years = (
                f"{info.year_min}–{info.year_max}"
                if info.year_min and info.year_max
                else "years unknown"
            )
            lines.append(f"- {info.key}: {info.description} {info.documents} documents, {years}.")
            if info.courts:
                courts = ", ".join(
                    f"{c.code} = {c.name} ({c.documents})"
                    for c in sorted(info.courts, key=lambda c: (c.rank, c.name))
                )
                lines.append(f"  Court codes: {courts}.")
        return "\n".join(lines)


# Weaviate returns at most 100 groups unless told otherwise, which would report
# every collection as exactly 100 documents. Far above the corpus size.
_MAX_GROUPS = 100_000


def _document_count(client: WeaviateClient, class_name: str, filters=None) -> int:
    response = client.collections.use(class_name).aggregate.over_all(
        group_by=GroupByAggregate(prop="doc_id", limit=_MAX_GROUPS), total_count=True, filters=filters
    )
    return len(response.groups)


def build_catalog(client: WeaviateClient) -> Catalog:
    infos = []
    for key in COLLECTIONS:
        class_name = CLASS_NAMES[key]
        handle = client.collections.use(class_name)

        totals = handle.aggregate.over_all(
            total_count=True, return_metrics=Metrics("year").integer(minimum=True, maximum=True)
        )
        year = totals.properties.get("year")

        courts = []
        if key == "case_law":
            by_court = handle.aggregate.over_all(
                group_by=GroupByAggregate(prop="court_code", limit=_MAX_GROUPS)
            )
            for group in by_court.groups:
                code = str(group.grouped_by.value)
                known = COURTS.get(code)
                courts.append(
                    CourtInfo(
                        code=code,
                        name=court_name(code),
                        rank=known.rank if known else 99,
                        documents=_document_count(
                            client, class_name, Filter.by_property("court_code").equal(code)
                        ),
                    )
                )

        infos.append(
            CollectionInfo(
                key=key,
                label=LABELS[key],
                description=DESCRIPTIONS[key],
                documents=_document_count(client, class_name),
                passages=totals.total_count or 0,
                year_min=int(year.minimum) if year and year.minimum is not None else None,
                year_max=int(year.maximum) if year and year.maximum is not None else None,
                courts=sorted(courts, key=lambda c: (c.rank, c.name)),
            )
        )
    return Catalog(collections=infos)


class CatalogHolder:
    """The current catalog, rebuilt from the database once it's older than `ttl`."""

    def __init__(self, client: WeaviateClient, ttl_seconds: float):
        self._client = client
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._catalog: Catalog | None = None
        self._built_at = 0.0

    def current(self) -> Catalog:
        # Double-checked under the lock so concurrent requests at expiry don't
        # all rebuild, but the common path never blocks on it.
        if self._catalog is not None and time.monotonic() - self._built_at < self._ttl:
            return self._catalog
        with self._lock:
            if self._catalog is None or time.monotonic() - self._built_at >= self._ttl:
                self._catalog = build_catalog(self._client)
                self._built_at = time.monotonic()
            return self._catalog

    def refresh(self) -> Catalog:
        with self._lock:
            self._catalog = build_catalog(self._client)
            self._built_at = time.monotonic()
            return self._catalog
