"""Background ingestion jobs.

Parsing, embedding and indexing a document takes seconds to minutes; holding an
HTTP connection open for it means a burst of uploads occupies a worker each and
the client has nothing to show but a spinner. Requests now return a job id
immediately and the work continues behind them.

Validation and malware scanning deliberately stay on the request path. A bad
file should be refused while the user is still looking at the upload, not
accepted and failed silently a minute later.

Concurrency is bounded rather than unlimited. The providers behind this pipeline
are rate-limited, and firing every queued document at them at once produces
429s, long retry backoffs, and jobs that look hung - which is exactly how the
stalls earlier in this project's history happened.

Scope: jobs live in this process. A restart loses in-flight work, and status for
a job is only known to the instance that accepted it. That is fine for a single
container and is the seam to replace with Redis/Celery when there is more than
one - `JobRegistry` is the only thing that would need swapping.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "succeeded", "failed"]


@dataclass
class Job:
    id: str
    tenant: str
    source: str
    status: JobStatus = "queued"
    chunks_indexed: int | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return {
            "job_id": self.id,
            "source": self.source,
            "status": self.status,
            "chunks_indexed": self.chunks_indexed,
            "error": self.error,
        }


class JobRegistry:
    """Tracks jobs and runs them with bounded concurrency.

    Entries are kept after completion so a client that polls a moment late still
    sees the outcome, and evicted oldest-first so a long-lived process doesn't
    accumulate them without limit.
    """

    def __init__(self, max_concurrency: int = 2, max_entries: int = 500):
        self._jobs: dict[str, Job] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_entries = max_entries
        self._tasks: set[asyncio.Task] = set()

    def get(self, job_id: str, tenant: str) -> Job | None:
        """Fetch a job, scoped to the tenant that created it.

        Tenant-checked for the same reason /files is: a job id shouldn't let one
        session read another's filenames or failures.
        """
        job = self._jobs.get(job_id)
        if job is None or job.tenant != tenant:
            return None
        return job

    def _evict_if_full(self) -> None:
        if len(self._jobs) < self._max_entries:
            return
        finished = [j for j in self._jobs.values() if j.status in ("succeeded", "failed")]
        for job in sorted(finished, key=lambda j: j.updated_at)[: len(finished) // 2 or 1]:
            self._jobs.pop(job.id, None)

    def submit(self, tenant: str, source: str, work, on_success=None, on_finish=None) -> Job:
        """Register a job and start it.

        `work` is a zero-argument sync callable returning the chunk count.
        `on_success` runs only when it succeeds (cache invalidation); `on_finish`
        always runs (releasing the upload's spool file), which is why they are
        separate rather than one callback.
        """
        self._evict_if_full()
        job = Job(id=str(uuid.uuid4()), tenant=tenant, source=source)
        self._jobs[job.id] = job

        task = asyncio.create_task(self._run(job, work, on_success, on_finish))
        # Held so the task isn't garbage collected mid-flight, which asyncio
        # permits for tasks nobody references.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: Job, work, on_success, on_finish) -> None:
        from asyncer import asyncify

        async with self._semaphore:
            job.status = "running"
            job.updated_at = time.time()
            try:
                job.chunks_indexed = await asyncify(work)()
                job.status = "succeeded"
                if on_success is not None:
                    on_success()
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                logger.exception("ingestion job %s failed for %s", job.id, job.source)
            finally:
                job.updated_at = time.time()
                if on_finish is not None:
                    on_finish()
