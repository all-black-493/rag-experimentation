import time
from collections.abc import Generator
from contextlib import contextmanager

import weaviate
from weaviate.client import WeaviateClient
from weaviate.exceptions import WeaviateConnectionError, WeaviateStartUpError

from app.config import Settings

_MAX_CONNECT_ATTEMPTS = 5
_INITIAL_BACKOFF_SECONDS = 1.0


def _connect_with_retry(settings: Settings) -> WeaviateClient:
    """Connect to Weaviate, retrying with backoff while the server is still starting up."""
    backoff = _INITIAL_BACKOFF_SECONDS
    for attempt in range(1, _MAX_CONNECT_ATTEMPTS + 1):
        try:
            return weaviate.connect_to_local(
                host=settings.weaviate_host,
                port=settings.weaviate_port,
                grpc_port=settings.weaviate_grpc_port,
            )
        except (WeaviateConnectionError, WeaviateStartUpError):
            if attempt == _MAX_CONNECT_ATTEMPTS:
                raise
            time.sleep(backoff)
            backoff *= 2
    raise AssertionError("unreachable")


@contextmanager
def weaviate_client(settings: Settings) -> Generator[WeaviateClient]:
    """Open a Weaviate connection for the given settings, closing it on exit."""
    client = _connect_with_retry(settings)
    try:
        yield client
    finally:
        client.close()
