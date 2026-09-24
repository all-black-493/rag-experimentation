"""Who is watching a matter, and what to tell them when it changes.

Indexing a document takes seconds to minutes, and its progress is a handful of
state changes rather than a stream of tokens: the client wants to hear when the
status moves and otherwise wants to be left alone. Polling costs a request a
second per open tab and still shows the change late. This publishes the matter
the moment the store writes it.

`publish` is called from the ingest worker thread; subscribers are served on the
event loop, so the hand-off goes through `call_soon_threadsafe`, as it does for
a workflow run. A subscriber that has stopped reading is dropped rather than
allowed to grow without limit - a stalled reader must not hold the writer.

What a subscriber gets is a queue rather than an iterator, because the route
has to interleave a heartbeat with the wait: cancelling a pending `anext` on an
async generator ends the generator, while cancelling `Queue.get` does not.
"""

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from app.matters.models import Matter

logger = logging.getLogger(__name__)

# A slow reader is one that hasn't drained while a document was indexed. Well
# past any real burst: a document's whole life is a handful of writes.
MAX_PENDING = 64


class MatterEvents:
    """A change feed per matter, for as long as someone is listening."""

    def __init__(self) -> None:
        # Bound when the first client subscribes, not here: this is built while
        # the app starts, which is not always on the loop that ends up serving
        # requests, and publishing to the wrong loop is a silent hang rather
        # than an error.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: dict[str, list[asyncio.Queue[Matter]]] = {}

    def publish(self, matter: Matter) -> None:
        """Announce a matter's new state. Safe to call from any thread."""
        if self._loop is None or matter.id not in self._subscribers:
            return
        self._loop.call_soon_threadsafe(self._deliver, matter)

    def _deliver(self, matter: Matter) -> None:
        for queue in list(self._subscribers.get(matter.id, ())):
            if queue.qsize() >= MAX_PENDING:
                logger.warning("dropping a matter event: subscriber is not reading")
                continue
            queue.put_nowait(matter)

    @contextmanager
    def watch(self, matter_id: str) -> Iterator[asyncio.Queue[Matter]]:
        """A queue of this matter's new states, for the life of the block."""
        self._loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Matter] = asyncio.Queue()
        self._subscribers.setdefault(matter_id, []).append(queue)
        try:
            yield queue
        finally:
            watchers = self._subscribers.get(matter_id, [])
            if queue in watchers:
                watchers.remove(queue)
            if not watchers:
                self._subscribers.pop(matter_id, None)

    def watching(self, matter_id: str) -> int:
        return len(self._subscribers.get(matter_id, ()))
