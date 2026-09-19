"""The two corpus collections, declared explicitly.

Explicit rather than autoschema, for two reasons that already bit this project.
Autoschema types a property from the shape of the first value it sees: a
32-character hex id became a `uuid` and came back reshaped, so no citation could
find its file. And it can't know that `url` should be one token for exact
filtering, that `parent_text` should never be BM25-searched, or that dates are
dates. Declaring the schema here makes those decisions reviewable, and
`ensure_collections` makes creating them idempotent so startup and the ingest
CLI can both call it.

No multi-tenancy: the corpus is shared by every reader.
"""

from weaviate.classes.config import Configure, DataType, Property, Tokenization
from weaviate.client import WeaviateClient

from app.metadata import CLASS_NAMES, Collection

# Properties every chunk has, whichever collection it lives in.
_COMMON = [
    # What gets matched, reranked and quoted.
    Property(name="text", data_type=DataType.TEXT),
    # What the model reads. Indexed for neither search nor filtering: it is a
    # superset of `text` and neighbours, so searching it would double-count.
    Property(
        name="parent_text",
        data_type=DataType.TEXT,
        index_searchable=False,
        index_filterable=False,
    ),
    # Searchable so BM25 can match "Traffic Act" or a party's name in the title.
    Property(name="title", data_type=DataType.TEXT),
    # One token each: these are identities to filter on, not text to search.
    Property(
        name="url",
        data_type=DataType.TEXT,
        tokenization=Tokenization.FIELD,
        index_searchable=False,
    ),
    Property(
        name="doc_id",
        data_type=DataType.TEXT,
        tokenization=Tokenization.FIELD,
        index_searchable=False,
    ),
    Property(name="chunk_index", data_type=DataType.INT),
    # Year decided (judgments) or enacted (Acts): what a year-range filter means.
    Property(name="year", data_type=DataType.INT, index_range_filters=True),
    # The point-in-time version Kenya Law served.
    Property(name="version_date", data_type=DataType.DATE),
]

_PROPERTIES: dict[Collection, list[Property]] = {
    "legislation": _COMMON,
    "case_law": [
        *_COMMON,
        Property(
            name="court_code",
            data_type=DataType.TEXT,
            tokenization=Tokenization.FIELD,
            index_searchable=False,
        ),
        Property(name="court", data_type=DataType.TEXT, index_searchable=False),
        Property(name="decision_date", data_type=DataType.DATE, index_range_filters=True),
    ],
}

# Properties handed back with every search hit. Everything a citation needs;
# nothing it doesn't.
RETURN_PROPERTIES: dict[Collection, list[str]] = {
    collection: [p.name for p in properties] for collection, properties in _PROPERTIES.items()
}


def ensure_collections(client: WeaviateClient) -> list[str]:
    """Create any corpus collection that doesn't exist yet. Returns those created."""
    created = []
    for collection, class_name in CLASS_NAMES.items():
        if client.collections.exists(class_name):
            continue
        client.collections.create(
            name=class_name,
            # Vectors come from our own embedder, at ingest and at query time,
            # so the same model - and the same query prefix - is used for both.
            vector_config=Configure.Vectors.self_provided(),
            properties=_PROPERTIES[collection],
        )
        created.append(class_name)
    return created
