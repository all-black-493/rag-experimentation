import tempfile
from pathlib import Path

from asyncer import asyncify
from fastapi import APIRouter, HTTPException, Request, UploadFile

from app.api.schemas import IngestResponse, IngestUrlRequest
from app.config import get_settings
from app.dependencies import SettingsDep, TenantDep, VectorStoreDep
from app.ingestion.pipeline import ingest_file, ingest_url
from app.ingestion.validation import UploadValidationError, validate_upload
from app.rate_limit import limiter

router = APIRouter(prefix="/ingest", tags=["ingestion"])
_rate_limit = get_settings().rate_limit_ingest


@router.post("/file")
@limiter.limit(_rate_limit)
async def ingest_uploaded_file(
    request: Request,
    file: UploadFile,
    vector_store: VectorStoreDep,
    settings: SettingsDep,
    tenant: TenantDep,
) -> IngestResponse:
    display_name = file.filename or "upload"
    suffix = Path(display_name).suffix
    content = await file.read()

    try:
        validate_upload(display_name, content, settings.max_upload_size_mb * 1024 * 1024)
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(content)
        tmp.flush()
        chunk_count = await asyncify(ingest_file)(
            Path(tmp.name), vector_store, settings, tenant=tenant, display_name=display_name
        )

    return IngestResponse(source=display_name, chunks_indexed=chunk_count)


@router.post("/url")
@limiter.limit(_rate_limit)
async def ingest_from_url(
    request: Request,
    payload: IngestUrlRequest,
    vector_store: VectorStoreDep,
    settings: SettingsDep,
    tenant: TenantDep,
) -> IngestResponse:
    chunk_count = await asyncify(ingest_url)(payload.url, vector_store, settings, tenant=tenant)
    return IngestResponse(source=payload.url, chunks_indexed=chunk_count)
