"""Matters: the user's own documents, indexed beside the corpus.

Validation runs on the request so a bad file is refused while the user is
looking at it; parsing, embedding and indexing run as a job, and the document's
status on the matter is how the client follows it.
"""

import asyncio
from functools import partial

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.schemas import DocumentAccepted, Matter, MatterCreate
from app.config import get_settings
from app.corpus.ids import content_id
from app.dependencies import (
    ClientDep,
    IngestDep,
    JobsDep,
    MatterEventsDep,
    MatterStoreDep,
    RetrievalCacheDep,
    SettingsDep,
)
from app.matters.delete import delete_document, delete_matter
from app.matters.ingest import ensure_tenant
from app.matters.loaders import UploadError, validate
from app.matters.models import MatterDocument
from app.rate_limit import limiter

router = APIRouter(prefix="/matters", tags=["matters"])
_upload_limit = get_settings().rate_limit_upload

_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


def _require(store, matter_id: str) -> Matter:
    matter = store.get(matter_id)
    if matter is None:
        raise HTTPException(status_code=404, detail="No such matter")
    return matter


@router.get("")
async def list_matters(store: MatterStoreDep) -> list[Matter]:
    return store.list()


@router.post("", status_code=201)
async def create_matter(payload: MatterCreate, store: MatterStoreDep, client: ClientDep) -> Matter:
    matter = store.create(payload.name)
    # Created now rather than on first upload, so a query against an empty
    # matter finds nothing instead of failing.
    ensure_tenant(client, matter.id)
    return matter


@router.get("/{matter_id}")
async def get_matter(matter_id: str, store: MatterStoreDep) -> Matter:
    return _require(store, matter_id)


@router.get("/{matter_id}/events", response_class=EventSourceResponse)
async def follow_matter(
    matter_id: str, store: MatterStoreDep, events: MatterEventsDep, settings: SettingsDep
):
    """The matter now, then each time it changes, until nothing is indexing.

    Every write to a matter arrives here, so a client watching an upload sees
    the status move instead of asking for it. The stream ends when the last
    document is indexed or has failed - there is nothing further to say, and a
    browser tab shouldn't hold a connection open to hear it. A comment goes out
    every few seconds meanwhile, because indexing a long PDF says nothing for
    minutes and an idle connection gets closed by whatever sits in between.
    """
    matter = _require(store, matter_id)
    with events.watch(matter_id) as changes:
        yield ServerSentEvent(data=matter, event="matter")
        while matter.indexing:
            try:
                matter = await asyncio.wait_for(
                    changes.get(), timeout=settings.sse_heartbeat_seconds
                )
            except TimeoutError:
                yield ServerSentEvent(comment="keep-alive")
                continue
            yield ServerSentEvent(data=matter, event="matter")


@router.delete("/{matter_id}", status_code=204)
async def remove_matter(matter_id: str, store: MatterStoreDep, client: ClientDep) -> None:
    if not delete_matter(client, store, matter_id):
        raise HTTPException(status_code=404, detail="No such matter")


@router.post("/{matter_id}/documents", status_code=202)
@limiter.limit(_upload_limit)
async def upload_document(
    request: Request,
    matter_id: str,
    file: UploadFile,
    store: MatterStoreDep,
    settings: SettingsDep,
    jobs: JobsDep,
    ingest: IngestDep,
    retrieval_cache: RetrievalCacheDep,
) -> DocumentAccepted:
    """Accept a document and index it in the background.

    The same bytes uploaded twice land on the same id, so a retried upload is
    re-indexed in place rather than duplicated.
    """
    _require(store, matter_id)
    name = file.filename or "document"
    content = await file.read()
    try:
        kind = validate(name, content, settings.max_upload_size_mb * 1024 * 1024)
    except UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc_id = content_id(content)
    store.save_file(matter_id, doc_id, f".{name.rsplit('.', 1)[-1].lower()}", content)
    store.add_document(
        matter_id, MatterDocument(doc_id=doc_id, name=name, kind=kind, bytes=len(content))
    )
    job = jobs.submit(
        matter_id,
        name,
        partial(ingest, matter_id, doc_id),
        on_finish=partial(retrieval_cache.invalidate_namespace, matter_id),
    )
    return DocumentAccepted(matter_id=matter_id, doc_id=doc_id, job_id=job.id)


@router.delete("/{matter_id}/documents/{doc_id}", status_code=204)
async def remove_document(
    matter_id: str,
    doc_id: str,
    store: MatterStoreDep,
    client: ClientDep,
    retrieval_cache: RetrievalCacheDep,
) -> None:
    if not delete_document(client, store, matter_id, doc_id):
        raise HTTPException(status_code=404, detail="No such document in this matter")
    retrieval_cache.invalidate_namespace(matter_id)


@router.get("/{matter_id}/files/{doc_id}")
async def get_file(matter_id: str, doc_id: str, store: MatterStoreDep) -> FileResponse:
    """The original, as uploaded. Range requests are honoured, so a PDF viewer
    can fetch one page of a long document."""
    matter = _require(store, matter_id)
    document = matter.document(doc_id)
    path = store.file_path(matter_id, doc_id)
    if document is None or path is None:
        raise HTTPException(status_code=404, detail="No such document in this matter")
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        filename=document.name,
        content_disposition_type="inline",
    )
