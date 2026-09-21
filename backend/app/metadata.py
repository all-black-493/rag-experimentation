"""The shared vocabulary for what can be searched.

Two corpus collections, split by what kind of law a document is. They have
different metadata - a judgment has a court and a decision date, an Act has a
year of enactment and a point-in-time version - so they get different schemas
and the planner routes between them rather than filtering one pile. A third,
`matter`, holds the user's own documents, partitioned per matter.

Set once at ingestion and carried immutably through retrieval. Never inferred
from LLM output: citations are built from this, not from anything the model
says about a source.
"""

from typing import Literal

Collection = Literal["legislation", "case_law", "matter"]

# The shared corpus. `matter` is in scope only when a request names a matter.
COLLECTIONS: tuple[Collection, ...] = ("legislation", "case_law")
MATTER: Collection = "matter"

# Weaviate class names. Kept separate from the API vocabulary so the wire format
# never depends on how the database happens to spell things.
CLASS_NAMES: dict[Collection, str] = {
    "legislation": "Legislation",
    "case_law": "CaseLaw",
    "matter": "MatterDocument",
}

LABELS: dict[Collection, str] = {
    "legislation": "Legislation",
    "case_law": "Case law",
    "matter": "Matter",
}
