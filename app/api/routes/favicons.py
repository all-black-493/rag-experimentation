from asyncer import asyncify
from fastapi import APIRouter, HTTPException, Response

from app.favicons import get_or_fetch_favicon

router = APIRouter(prefix="/favicons", tags=["favicons"])


@router.get("/{domain}")
async def get_favicon(domain: str) -> Response:
    result = await asyncify(get_or_fetch_favicon)(domain)
    if result is None:
        raise HTTPException(status_code=404, detail="No favicon available for this domain")

    content, content_type = result
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
