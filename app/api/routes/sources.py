from asyncer import asyncify
from fastapi import APIRouter, HTTPException, Response

from app.api.schemas import SourceSummary
from app.dependencies import RetrievalCacheDep, SettingsDep, TenantDep, WeaviateClientDep
from app.ingestion.dedupe import list_ingested
from app.ingestion.deletion import delete_document
from app.storage import UPLOADS_DIR

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("")
async def list_sources(tenant: TenantDep) -> list[SourceSummary]:
    """What this session has indexed.

    Lets the sources list survive a reload: without it the UI only knows about
    documents added in the current page view, so a returning user can't see - or
    remove - what they added yesterday.
    """
    return [SourceSummary(**entry) for entry in list_ingested(UPLOADS_DIR, tenant)]


@router.delete("/{doc_id}", status_code=204)
async def delete_source(
    doc_id: str,
    tenant: TenantDep,
    client: WeaviateClientDep,
    settings: SettingsDep,
    retrieval_cache: RetrievalCacheDep,
) -> Response:
    """Remove a document and everything derived from it.

    Blocking work (a Weaviate delete plus a few unlinks) on a worker thread, and
    the tenant's cached retrievals are dropped afterwards - otherwise the next
    question could still be answered from chunks that no longer exist.
    """
    deleted = await asyncify(delete_document)(
        client, settings.weaviate_collection, UPLOADS_DIR, tenant, doc_id
    )
    if not deleted:
        # 404 rather than 403 for another session's document, so a doc_id can't
        # be used to probe what other sessions have indexed.
        raise HTTPException(status_code=404, detail="No such document in this session")

    retrieval_cache.invalidate_namespace(tenant)
    return Response(status_code=204)
