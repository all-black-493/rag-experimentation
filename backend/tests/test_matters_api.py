"""The /matters routes, over a real store on disk and fakes for Weaviate and the job."""

import json
from pathlib import Path

import pymupdf
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import matters
from app.caching import TTLCache
from app.matters.events import MatterEvents
from app.matters.store import MatterStore


class InlineJobs:
    """Runs the job on submit, so a test sees the outcome without an event loop."""

    def __init__(self):
        self.submitted = []

    def submit(self, scope, subject, work, on_finish=None):
        self.submitted.append(subject)
        try:
            work()
        finally:
            if on_finish:
                on_finish()

        class Job:
            id = "job-1"

        return Job()


class FakeCollections:
    def __init__(self):
        self.deleted = []
        self.removed_tenants = []
        self._tenant = None

    def use(self, name):
        return self

    def with_tenant(self, tenant):
        self._tenant = tenant
        return self

    @property
    def tenants(self):
        return self

    def exists(self, tenant):
        return True

    def create(self, tenants):
        raise AssertionError("an existing tenant is never created again")

    def remove(self, tenants):
        self.removed_tenants.extend(tenants)

    @property
    def data(self):
        return self

    def delete_many(self, where):
        self.deleted.append(self._tenant)


class FakeClient:
    def __init__(self):
        self.collections = FakeCollections()


def make_pdf(path: Path) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Clause 3.1 Rent is KSh 120,000 per month.")
    doc.save(str(path))
    return path.read_bytes()


def make_app(tmp_path: Path):
    app = FastAPI()
    app.include_router(matters.router)
    events = MatterEvents()
    app.state.matter_events = events
    app.state.matters = MatterStore(tmp_path / "matters", on_change=events.publish)
    app.state.jobs = InlineJobs()
    app.state.client = FakeClient()
    app.state.retrieval_cache = TTLCache(60)
    app.state.limiter = matters.limiter

    def ingest(matter_id: str, doc_id: str) -> int:
        app.state.matters.update_document(matter_id, doc_id, status="indexed", chunks=1, pages=1)
        return 1

    app.state.ingest = ingest
    return app


def test_a_matter_takes_documents_and_serves_them_back(tmp_path):
    app = make_app(tmp_path)
    client = TestClient(app)

    created = client.post("/matters", json={"name": "Karanja v Otieno"})
    assert created.status_code == 201
    matter_id = created.json()["id"]
    assert [m["id"] for m in client.get("/matters").json()] == [matter_id]

    content = make_pdf(tmp_path / "lease.pdf")
    accepted = client.post(
        f"/matters/{matter_id}/documents", files={"file": ("lease.pdf", content, "application/pdf")}
    )
    assert accepted.status_code == 202
    doc_id = accepted.json()["doc_id"]
    assert app.state.jobs.submitted == ["lease.pdf"]

    matter = client.get(f"/matters/{matter_id}").json()
    document = matter["documents"][0]
    assert document["doc_id"] == doc_id
    assert (document["status"], document["chunks"], document["pages"]) == ("indexed", 1, 1)

    served = client.get(f"/matters/{matter_id}/files/{doc_id}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "application/pdf"
    assert served.content == content
    # A viewer asks for one page at a time.
    partial = client.get(f"/matters/{matter_id}/files/{doc_id}", headers={"range": "bytes=0-9"})
    assert partial.status_code == 206 and partial.content == content[:10]

    removed = client.delete(f"/matters/{matter_id}/documents/{doc_id}")
    assert removed.status_code == 204
    assert app.state.client.collections.deleted == [matter_id]
    assert client.get(f"/matters/{matter_id}").json()["documents"] == []
    assert client.get(f"/matters/{matter_id}/files/{doc_id}").status_code == 404

    assert client.delete(f"/matters/{matter_id}").status_code == 204
    assert app.state.client.collections.removed_tenants == [matter_id]
    assert client.get(f"/matters/{matter_id}").status_code == 404


def test_bad_uploads_are_refused_on_the_request(tmp_path):
    app = make_app(tmp_path)
    client = TestClient(app)
    matter_id = client.post("/matters", json={"name": "m"}).json()["id"]

    refused = client.post(
        f"/matters/{matter_id}/documents",
        files={"file": ("deck.pptx", b"PK\x03\x04", "application/x")},
    )
    assert refused.status_code == 400 and "Unsupported" in refused.json()["detail"]
    assert app.state.jobs.submitted == []
    assert client.get(f"/matters/{matter_id}").json()["documents"] == []

    missing = client.post("/matters/000000000000/documents", files={"file": ("a.txt", b"x")})
    assert missing.status_code == 404
    assert client.get("/matters/not-an-id").status_code == 404


def test_the_event_stream_reports_a_document_until_it_is_indexed(tmp_path):
    """A client that opens the stream is told the matter's state at once, then
    each change, and the stream ends when nothing is indexing - which is the
    whole of what the client used to poll for."""
    app = make_app(tmp_path)
    client = TestClient(app)
    matter_id = client.post("/matters", json={"name": "Wanjiru v Otieno"}).json()["id"]
    client.post(
        f"/matters/{matter_id}/documents",
        files={"file": ("lease.pdf", make_pdf(tmp_path / "lease.pdf"), "application/pdf")},
    )

    with client.stream("GET", f"/matters/{matter_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        states = [json.loads(line.removeprefix("data:")) for line in response.iter_lines()
                  if line.startswith("data:")]

    # The fake job indexes on submit, so by the time the stream opens the work
    # is done: one state, complete, and then the server closes.
    assert [d["status"] for d in states[-1]["documents"]] == ["indexed"]
    assert states[-1]["name"] == "Wanjiru v Otieno"
