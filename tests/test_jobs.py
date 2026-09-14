import asyncio

import pytest

from app.jobs import JobRegistry


async def _settle(registry: JobRegistry, job, timeout: float = 2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while job.status in ("queued", "running"):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"job stuck in {job.status}")
        await asyncio.sleep(0.01)
    return job


@pytest.mark.asyncio
async def test_successful_job_reports_chunk_count():
    registry = JobRegistry()

    job = registry.submit("tenant", "doc.pdf", lambda: 7)
    assert job.status == "queued"

    await _settle(registry, job)
    assert job.status == "succeeded"
    assert job.chunks_indexed == 7


@pytest.mark.asyncio
async def test_failure_is_surfaced_on_the_job_not_raised():
    """The request already returned, so the error has to reach the client here."""
    registry = JobRegistry()

    def boom():
        raise RuntimeError("provider exploded")

    job = await _settle(registry, registry.submit("tenant", "doc.pdf", boom))

    assert job.status == "failed"
    assert "provider exploded" in job.error


@pytest.mark.asyncio
async def test_cleanup_runs_whether_the_job_succeeds_or_fails():
    """The upload's spool file must not be leaked by a failed job."""
    registry = JobRegistry()
    finished = []

    await _settle(
        registry,
        registry.submit("t", "ok", lambda: 1, on_finish=lambda: finished.append("ok")),
    )

    def boom():
        raise RuntimeError("nope")

    await _settle(
        registry, registry.submit("t", "bad", boom, on_finish=lambda: finished.append("bad"))
    )

    assert sorted(finished) == ["bad", "ok"]


@pytest.mark.asyncio
async def test_on_success_does_not_run_for_a_failed_job():
    """Cache invalidation shouldn't fire for a document that never indexed."""
    registry = JobRegistry()
    invalidated = []

    def boom():
        raise RuntimeError("nope")

    await _settle(
        registry, registry.submit("t", "bad", boom, on_success=lambda: invalidated.append(1))
    )

    assert invalidated == []


@pytest.mark.asyncio
async def test_jobs_are_scoped_to_their_tenant():
    """A job id must not let another session read what's being ingested."""
    registry = JobRegistry()
    job = registry.submit("tenant-a", "secret.pdf", lambda: 1)

    assert registry.get(job.id, "tenant-a") is not None
    assert registry.get(job.id, "tenant-b") is None


@pytest.mark.asyncio
async def test_concurrency_is_bounded():
    """More parallelism than this buys 429s from the embedding provider."""
    registry = JobRegistry(max_concurrency=2)
    concurrent = 0
    peak = 0

    def work():
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        # Sleeping in the worker thread, which is where real ingestion blocks.
        import time

        time.sleep(0.05)
        concurrent -= 1
        return 1

    jobs = [registry.submit("t", f"doc-{i}", work) for i in range(6)]
    for job in jobs:
        await _settle(registry, job, timeout=5.0)

    assert peak <= 2
