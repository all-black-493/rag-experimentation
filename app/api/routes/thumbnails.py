from fastapi import APIRouter, HTTPException, Response

from app.thumbnails import get_cached_thumbnail

router = APIRouter(prefix="/thumbnails", tags=["thumbnails"])


@router.get("/{key}")
async def get_thumbnail(key: str) -> Response:
    """Serve a cached web page preview image.

    Cache-only, never fetching on demand: these are written at ingestion, so a
    miss means there was no preview image rather than "try again later".
    """
    result = get_cached_thumbnail(key)
    if result is None:
        raise HTTPException(status_code=404, detail="No thumbnail for this key")

    content, content_type = result
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )
