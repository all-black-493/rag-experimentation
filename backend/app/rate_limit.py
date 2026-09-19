"""Per-client rate limiting. Anonymous use has no auth, so this is the abuse guard.

Applied as a default limit through the ASGI middleware rather than per-route
decorators: the streaming route is an async generator, which the decorator
can't wrap, and the middleware covers every route uniformly.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import get_settings
from app.proxy_auth import TRUSTED_PROXY_STATE


def rate_limit_key(request: Request) -> str:
    """The client's address - through the proxy, when the proxy has proven itself.

    Behind the frontend's server-side proxy every request arrives from one
    address, so keying on the socket peer would put every user in one bucket.
    X-Forwarded-For is trusted only on requests that carried the proxy secret;
    an arbitrary caller can't spoof its way into someone else's bucket, or out
    of its own.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and getattr(request.state, TRUSTED_PROXY_STATE, False):
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key, default_limits=[get_settings().rate_limit_query])
