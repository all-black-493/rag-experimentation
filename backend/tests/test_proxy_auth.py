from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.proxy_auth import PROXY_SECRET_HEADER, require_proxy_secret


def make_client(monkeypatch, secret: str) -> TestClient:
    monkeypatch.setattr("app.proxy_auth.get_settings", lambda: Settings(proxy_secret=secret))
    app = FastAPI()
    app.middleware("http")(require_proxy_secret)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/query")
    def query():
        return {"answer": "x"}

    return TestClient(app)


def test_requests_without_the_secret_are_refused(monkeypatch):
    client = make_client(monkeypatch, "s3cret")

    assert client.get("/query").status_code == 401
    assert client.get("/query", headers={PROXY_SECRET_HEADER: "wrong"}).status_code == 401


def test_requests_with_the_secret_pass(monkeypatch):
    client = make_client(monkeypatch, "s3cret")

    assert client.get("/query", headers={PROXY_SECRET_HEADER: "s3cret"}).status_code == 200


def test_health_stays_open_for_platform_checks(monkeypatch):
    client = make_client(monkeypatch, "s3cret")

    assert client.get("/health").status_code == 200


def test_gate_is_off_when_no_secret_is_configured(monkeypatch):
    """Local development and CI never set one and must keep working unchanged."""
    client = make_client(monkeypatch, "")

    assert client.get("/query").status_code == 200
