from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.dependencies import TenantDep
from app.storage import get_page_thumbnail_path, get_pdf_path

router = APIRouter(prefix="/files", tags=["files"])

# Thumbnails are immutable once rendered - the page they depict can't change
# without a new upload, which gets a new doc_id.
_THUMBNAIL_CACHE_CONTROL = "private, max-age=86400, immutable"


@router.get("/{doc_id}")
async def get_pdf(doc_id: str, tenant: TenantDep) -> FileResponse:
    path = get_pdf_path(tenant, doc_id)
    if path is None:
        raise HTTPException(status_code=404, detail="No such document in this session")
    return FileResponse(path, media_type="application/pdf")


@router.get("/{doc_id}/thumbnail/{page}")
async def get_page_thumbnail(doc_id: str, page: int, tenant: TenantDep) -> FileResponse:
    path = get_page_thumbnail_path(tenant, doc_id, page)
    if path is None:
        raise HTTPException(status_code=404, detail="No such page thumbnail in this session")
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": _THUMBNAIL_CACHE_CONTROL},
    )
