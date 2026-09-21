"""A workflow run: a job whose progress is a stream of events a client can follow.

A research memo takes tens of seconds and more than one model call. It runs
as a job so the request returns at once, and it reports as it goes so the
reader watches the passes happen rather than a spinner. Events are kept, so
a client that connects late - or reconnects - sees everything from the start.

The graph runs on a worker thread; `emit` hands each event to the event loop,
where subscribers are served. Nothing here knows what a research run is.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from app.jobs import Job, JobRegistry

_END = object()


@dataclass
class WorkflowRun:
    job: Job
    workflow: str
    question: str
    loop: asyncio.AbstractEventLoop
    events: list[dict] = field(default_factory=list)
    done: bool = False
    _subscribers: list[asyncio.Queue] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.job.id

    def emit(self, event: str, data: Any) -> None:
        """Record an event. Safe to call from the worker thread."""
        self.loop.call_soon_threadsafe(self._publish, {"event": event, "data": data})

    def finish(self) -> None:
        self.loop.call_soon_threadsafe(self._publish, _END)

    def _publish(self, item: Any) -> None:
        # On the loop thread: a snapshot in `follow` and this append never interleave.
        if item is _END:
            self.done = True
        else:
            self.events.append(item)
        for queue in self._subscribers:
            queue.put_nowait(item)

    async def follow(self) -> AsyncIterator[dict]:
        """Everything so far, then each new event as it lands, until the run ends."""
        queue: asyncio.Queue = asyncio.Queue()
        replay = list(self.events)
        finished = self.done
        if not finished:
            self._subscribers.append(queue)
        try:
            for item in replay:
                yield item
            if finished:
                return
            while True:
                item = await queue.get()
                if item is _END:
                    return
                yield item
        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def summary(self) -> dict:
        return {
            "job_id": self.id,
            "workflow": self.workflow,
            "question": self.question,
            "status": self.job.status,
            "error": self.job.error,
            "events": len(self.events),
            "done": self.done,
            "created_at": self.job.created_at,
        }


class WorkflowRuns:
    """Starts runs and keeps the recent ones so their events can be followed."""

    def __init__(self, jobs: JobRegistry, max_runs: int = 200):
        self._jobs = jobs
        self._runs: dict[str, WorkflowRun] = {}
        self._max = max_runs

    def get(self, job_id: str) -> WorkflowRun | None:
        return self._runs.get(job_id)

    def start(
        self, workflow: str, question: str, work: Callable[[WorkflowRun], None]
    ) -> WorkflowRun:
        """`work` runs on a worker thread and must call `run.finish()` when it is over."""
        self._evict()
        loop = asyncio.get_running_loop()
        holder: dict[str, WorkflowRun] = {}

        def job_work() -> None:
            work(holder["run"])

        job = self._jobs.submit(workflow, question, job_work)
        run = WorkflowRun(job=job, workflow=workflow, question=question, loop=loop)
        holder["run"] = run
        self._runs[job.id] = run
        return run

    def _evict(self) -> None:
        if len(self._runs) < self._max:
            return
        finished = sorted(
            (r for r in self._runs.values() if r.done), key=lambda r: r.job.updated_at
        )
        for run in finished[: len(finished) // 2 or 1]:
            self._runs.pop(run.id, None)
        # A registry full of unfinished runs keeps them all; it only ever grows
        # that way if callers start runs faster than they can finish.
        _ = time.time()
