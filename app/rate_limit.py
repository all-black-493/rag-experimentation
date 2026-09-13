from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.dependencies import SESSION_ID_PATTERN


def rate_limit_key(request: Request) -> str:
    """Rate-limit per session where one is given, otherwise per IP.

    Anonymous use means a session id is self-reported, not authenticated - the
    goal here is containing abuse from a given client, not verifying identity.
    """
    session_id = request.headers.get("x-session-id")
    if session_id and SESSION_ID_PATTERN.match(session_id):
        return session_id
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key)
