"""Background jobs: work that outlives the request that asked for it.

Parsing, embedding and indexing a document takes seconds to minutes; holding
the connection open for it would occupy a worker per upload and give the client
nothing but a spinner. Requests return at once and the work continues behind
them. Concurrency is bounded: the embedder is a CPU model and the providers
behind enrichment are rate-limited, so a burst of uploads queues rather than
stampedes.

Jobs live in this process. A restart loses in-flight work, and a job's status
is only known to the instance that accepted it - fine for one container, and
`JobRegistry` is the one thing to swap when there is more than one.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "succeeded", "failed"]


@dataclass
class Job:
    id: str
    # What the job belongs to - a matter - so status can be read back per owner.
    scope: str
    subject: str
    status: JobStatus = "queued"
    result: object = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobRegistry:
    """Tracks jobs and runs them with bounded concurrency.

    Finished entries are kept so a client polling a moment late still sees the
    outcome, and evicted oldest-first so a long-lived process doesn't collect
    them without limit.
    """

    def __init__(self, max_concurrency: int = 2, max_entries: int = 500):
        self._jobs: dict[str, Job] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._max_entries = max_entries
        self._tasks: set[asyncio.Task] = set()

    def get(self, job_id: str, scope: str) -> Job | None:
        job = self._jobs.get(job_id)
        return job if job is not None and job.scope == scope else None

    def submit(
        self,
        scope: str,
        subject: str,
        work: Callable[[], object],
        on_finish: Callable[[], None] | None = None,
    ) -> Job:
        """Register `work` - a zero-argument sync callable - and start it."""
        self._evict_if_full()
        job = Job(id=str(uuid.uuid4()), scope=scope, subject=subject)
        self._jobs[job.id] = job
        task = asyncio.create_task(self._run(job, work, on_finish))
        # Held so the task isn't garbage collected mid-flight, which asyncio
        # permits for tasks nobody references.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def _evict_if_full(self) -> None:
        if len(self._jobs) < self._max_entries:
            return
        finished = [j for j in self._jobs.values() if j.status in ("succeeded", "failed")]
        for job in sorted(finished, key=lambda j: j.updated_at)[: len(finished) // 2 or 1]:
            self._jobs.pop(job.id, None)

    async def _run(self, job: Job, work, on_finish) -> None:
        from asyncer import asyncify

        async with self._semaphore:
            job.status = "running"
            job.updated_at = time.time()
            try:
                job.result = await asyncify(work)()
                job.status = "succeeded"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                logger.exception("job %s failed for %s", job.id, job.subject)
            finally:
                job.updated_at = time.time()
                if on_finish is not None:
                    on_finish()
