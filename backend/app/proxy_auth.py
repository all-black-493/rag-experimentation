"""Refuse requests that didn't come through the trusted proxy.

In production the frontend's server-side proxy is the only client that should
reach this API, and it attaches a shared secret to every request. The backend's
own hostname is still public, so without this check anyone who found it could
run queries on the operator's API key - and skip whatever access control sits
in front of the frontend.

Off when PROXY_SECRET is unset, so local development and CI are unchanged.
"""

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import get_settings

PROXY_SECRET_HEADER = "x-proxy-secret"

# Set on request.state when the secret matched, so downstream code (the rate
# limiter) can trust forwarded headers from this request and no other.
TRUSTED_PROXY_STATE = "trusted_proxy"

# The platform's health check can't carry the header, and the endpoint reveals
# nothing beyond "the process is up".
_OPEN_PATHS = frozenset({"/health"})


async def require_proxy_secret(request: Request, call_next):
    expected = get_settings().proxy_secret
    if expected and request.url.path not in _OPEN_PATHS:
        supplied = request.headers.get(PROXY_SECRET_HEADER, "")
        # Constant-time so a wrong secret can't be narrowed down byte by byte.
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        setattr(request.state, TRUSTED_PROXY_STATE, True)
    return await call_next(request)
