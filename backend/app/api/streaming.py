"""Bridge a synchronous event generator onto the event loop as SSE.

The graph is synchronous and must run on one worker thread (the trace context
is thread-local). The response is async. A queue joins them: the producer thread
pushes each event with `call_soon_threadsafe`, the async side drains it. A
sentinel marks the end so the client sees a clean close rather than a hang.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from fastapi.sse import ServerSentEvent

from app.retrieval.run import StreamEvent

_END = object()


async def sse_events(
    events: Iterator[StreamEvent], *, finalize: Callable[[Any], Any]
) -> AsyncIterator[ServerSentEvent]:
    """Yield each StreamEvent as a ServerSentEvent, running the producer off-loop.

    `finalize` turns the `done` event's outcome into its wire model; every
    other event's data is already JSON-shaped.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def produce() -> None:
        try:
            for event in events:
                loop.call_soon_threadsafe(queue.put_nowait, event)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _END)

    producer = loop.run_in_executor(None, produce)
    try:
        while True:
            item = await queue.get()
            if item is _END:
                break
            data = finalize(item.data) if item.event == "done" else item.data
            yield ServerSentEvent(data=data, event=item.event)
    finally:
        await producer
