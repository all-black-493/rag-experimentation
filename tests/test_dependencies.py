from app.dependencies import get_tenant
from app.rate_limit import rate_limit_key


class FakeRequest:
    def __init__(self, headers: dict[str, str], client_host: str = "127.0.0.1"):
        self.headers = headers
        self.client = type("Client", (), {"host": client_host})()


def test_get_tenant_uses_valid_session_header():
    assert get_tenant("my-session-123") == "my-session-123"


def test_get_tenant_falls_back_when_header_missing():
    assert get_tenant(None) == "default"


def test_get_tenant_falls_back_when_header_has_invalid_characters():
    assert get_tenant("not a valid tenant id!") == "default"


def test_get_tenant_falls_back_when_header_too_long():
    assert get_tenant("a" * 65) == "default"


def test_rate_limit_key_prefers_session_header():
    request = FakeRequest(headers={"x-session-id": "abc-123"})
    assert rate_limit_key(request) == "abc-123"


def test_rate_limit_key_falls_back_to_ip_when_header_invalid():
    request = FakeRequest(headers={"x-session-id": "bad header!"})
    assert rate_limit_key(request) == "127.0.0.1"
