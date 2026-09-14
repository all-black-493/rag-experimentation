import tempfile
from functools import partial
from pathlib import Path

from asyncer import asyncify
from fastapi import APIRouter, HTTPException, Request, UploadFile

from app.api.schemas import IngestUrlRequest, JobResponse
from app.config import get_settings
from app.dependencies import (
    JobsDep,
    RetrievalCacheDep,
    SettingsDep,
    TenantDep,
    VectorStoreDep,
)
from app.ingestion.malware import MalwareFoundError, ScannerUnavailableError, scan
from app.ingestion.pipeline import ingest_file, ingest_url
from app.ingestion.validation import UploadValidationError, validate_upload
from app.rate_limit import limiter

router = APIRouter(prefix="/ingest", tags=["ingestion"])
_rate_limit = get_settings().rate_limit_ingest


@router.post("/file", status_code=202)
@limiter.limit(_rate_limit)
async def ingest_uploaded_file(
    request: Request,
    file: UploadFile,
    vector_store: VectorStoreDep,
    settings: SettingsDep,
    tenant: TenantDep,
    retrieval_cache: RetrievalCacheDep,
    jobs: JobsDep,
) -> JobResponse:
    """Accept an upload and index it in the background.

    Validation and the malware scan run here, synchronously, so a bad file is
    refused while the user is still looking at the upload rather than accepted
    and failed quietly a minute later. Only the slow part - parse, embed, index -
    is deferred.
    """
    display_name = file.filename or "upload"
    suffix = Path(display_name).suffix
    content = await file.read()

    try:
        validate_upload(display_name, content, settings.max_upload_size_mb * 1024 * 1024)
    except UploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if settings.malware_scan_enabled:
        try:
            await asyncify(scan)(
                content,
                settings.clamav_host,
                settings.clamav_port,
                settings.clamav_timeout_seconds,
            )
        except MalwareFoundError as exc:
            raise HTTPException(status_code=400, detail=f"File rejected: {exc}.") from exc
        except ScannerUnavailableError as exc:
            # Fail closed: an unscanned upload is not a cleared upload.
            raise HTTPException(
                status_code=503, detail="Malware scanning unavailable; upload refused."
            ) from exc

    # Spooled to a named file rather than held in memory: the job outlives this
    # request, so delete=False and the job removes it when it finishes.
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        spooled = Path(tmp.name)

    job = jobs.submit(
        tenant,
        display_name,
        partial(
            ingest_file,
            spooled,
            vector_store,
            settings,
            tenant=tenant,
            display_name=display_name,
        ),
        on_success=partial(retrieval_cache.invalidate_namespace, tenant),
        on_finish=partial(spooled.unlink, missing_ok=True),
    )
    return JobResponse(**job.as_dict())


@router.post("/url", status_code=202)
@limiter.limit(_rate_limit)
async def ingest_from_url(
    request: Request,
    payload: IngestUrlRequest,
    vector_store: VectorStoreDep,
    settings: SettingsDep,
    tenant: TenantDep,
    retrieval_cache: RetrievalCacheDep,
    jobs: JobsDep,
) -> JobResponse:
    job = jobs.submit(
        tenant,
        payload.url,
        partial(ingest_url, payload.url, vector_store, settings, tenant=tenant),
        on_success=partial(retrieval_cache.invalidate_namespace, tenant),
    )
    return JobResponse(**job.as_dict())


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, tenant: TenantDep, jobs: JobsDep) -> JobResponse:
    job = jobs.get(job_id, tenant)
    if job is None:
        # 404 rather than 403 for a job belonging to another session, so a job id
        # can't be used to probe what other sessions are ingesting.
        raise HTTPException(status_code=404, detail="No such job in this session")
    return JobResponse(**job.as_dict())
