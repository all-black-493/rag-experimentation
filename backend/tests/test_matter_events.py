"""The change feed a matter's clients follow, and the route that serves it.

The route is exercised directly rather than through TestClient: its generator
is meant to sit open while a worker thread indexes, and TestClient drives both
sides of that from one thread.
"""

import asyncio

import pytest

from app.api.routes.matters import follow_matter
from app.config import Settings
from app.matters.events import MAX_PENDING, MatterEvents
from app.matters.models import Matter, MatterDocument


def queued(name: str = "lease.pdf") -> MatterDocument:
    return MatterDocument(doc_id="a" * 40, name=name, kind="pdf", bytes=10)


class Store:
    """Just enough store for the route: the matter as it stands now."""

    def __init__(self, matter: Matter):
        self.matter = matter

    def get(self, matter_id: str) -> Matter | None:
        return self.matter if matter_id == self.matter.id else None


async def test_publishing_reaches_every_watcher_of_that_matter_and_no_other():
    events = MatterEvents()
    watched = Matter(id="0123456789ab", name="Watched")
    other = Matter(id="ffffffffffff", name="Other")

    with (
        events.watch(watched.id) as first,
        events.watch(watched.id) as second,
        events.watch(other.id) as elsewhere,
    ):
        events.publish(watched)
        await asyncio.sleep(0)
        assert first.get_nowait().name == "Watched"
        assert second.get_nowait().name == "Watched"
        assert elsewhere.empty()


async def test_nobody_watching_costs_nothing():
    """Indexing writes the matter on every step; with no client open, that must
    not queue work on the loop."""
    events = MatterEvents()
    events.publish(Matter(id="0123456789ab", name="Unwatched"))
    assert events.watching("0123456789ab") == 0


async def test_a_watcher_that_stops_reading_is_dropped_not_grown():
    events = MatterEvents()
    matter = Matter(id="0123456789ab", name="Stalled")
    with events.watch(matter.id) as queue:
        for _ in range(MAX_PENDING + 10):
            events.publish(matter)
            await asyncio.sleep(0)
        assert queue.qsize() == MAX_PENDING


async def test_watchers_are_forgotten_when_the_stream_ends():
    events = MatterEvents()
    with events.watch("0123456789ab"):
        assert events.watching("0123456789ab") == 1
    assert events.watching("0123456789ab") == 0


async def test_the_stream_holds_while_indexing_and_ends_when_it_finishes():
    events = MatterEvents()
    matter = Matter(id="0123456789ab", name="Karanja v Otieno", documents=[queued()])
    store = Store(matter)
    stream = follow_matter("0123456789ab", store, events, Settings(sse_heartbeat_seconds=30))

    opening = await anext(stream)
    assert opening.event == "matter"
    assert opening.data.documents[0].status == "queued"

    # Still indexing: the stream is waiting, not finished.
    pending = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.05)
    assert not pending.done()

    indexed = matter.model_copy(deep=True)
    indexed.documents[0].status = "indexed"
    events.publish(indexed)
    assert (await pending).data.documents[0].status == "indexed"

    # Nothing left to say: the next read ends the stream.
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_an_idle_stream_sends_a_comment_rather_than_falling_silent():
    """A long PDF says nothing for minutes, and something in between will close
    a connection that says nothing at all."""
    events = MatterEvents()
    matter = Matter(id="0123456789ab", name="Slow", documents=[queued()])
    settings = Settings(sse_heartbeat_seconds=0.01)
    stream = follow_matter("0123456789ab", Store(matter), events, settings)

    await anext(stream)
    beat = await anext(stream)
    assert beat.comment == "keep-alive"
    assert beat.data is None
    await stream.aclose()


async def test_a_matter_with_nothing_indexing_gets_one_state_and_a_close():
    events = MatterEvents()
    matter = Matter(id="0123456789ab", name="Settled")
    stream = follow_matter("0123456789ab", Store(matter), events, Settings())

    assert (await anext(stream)).data.name == "Settled"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
