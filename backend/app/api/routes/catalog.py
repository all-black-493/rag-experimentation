from fastapi import APIRouter

from app.dependencies import CatalogDep
from app.retrieval.catalog import Catalog

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("")
async def get_catalog(catalog: CatalogDep) -> Catalog:
    """What the corpus contains: collections, courts, year bounds, counts.

    The UI builds its filter rail from this rather than hardcoding a vocabulary,
    so it can never offer a court the corpus doesn't have.
    """
    return catalog
