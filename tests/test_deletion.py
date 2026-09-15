from types import SimpleNamespace

from app.ingestion.dedupe import already_ingested, content_id, record_ingestion
from app.ingestion.deletion import delete_document
from app.storage import get_pdf_path, save_page_thumbnail, save_pdf

COLLECTION = "Chunk"
DOC_ID = content_id(b"a document")


class FakeClient:
    """Just enough Weaviate to record what a delete asked for, and for which tenant."""

    def __init__(self):
        self.deletes: list[tuple[str, str]] = []

    @property
    def collections(self):
        return self

    def get(self, collection):
        return SimpleNamespace(with_tenant=lambda tenant: self._handle(collection, tenant))

    def _handle(self, collection, tenant):
        def delete_many(where):
            self.deletes.append((collection, tenant))
            return SimpleNamespace(successful=4)

        return SimpleNamespace(data=SimpleNamespace(delete_many=delete_many))


def ingested(tmp_path, tenant="t", doc_id=DOC_ID):
    record_ingestion(tmp_path, tenant, doc_id, source="a.pdf", source_type="pdf", chunks=4)


def test_deleting_removes_chunks_files_and_the_manifest_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)
    ingested(tmp_path)
    save_pdf("t", DOC_ID, b"content")
    save_page_thumbnail("t", DOC_ID, 1, b"png")
    client = FakeClient()

    assert delete_document(client, COLLECTION, tmp_path, "t", DOC_ID) is True

    assert client.deletes == [(COLLECTION, "t")]
    assert get_pdf_path("t", DOC_ID) is None
    # Without this the same file could never be re-uploaded: its id is a hash of
    # its content, so the re-upload would be skipped as already ingested.
    assert already_ingested(tmp_path, "t", DOC_ID) is None


def test_deleting_an_unknown_document_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)
    client = FakeClient()

    assert delete_document(client, COLLECTION, tmp_path, "t", DOC_ID) is False
    assert client.deletes == []


def test_a_tenant_cannot_delete_another_tenants_document(tmp_path, monkeypatch):
    """Reported as a plain miss, so a doc_id can't be used to probe other sessions."""
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)
    ingested(tmp_path, tenant="owner")
    save_pdf("owner", DOC_ID, b"content")
    client = FakeClient()

    assert delete_document(client, COLLECTION, tmp_path, "intruder", DOC_ID) is False

    assert client.deletes == []
    assert get_pdf_path("owner", DOC_ID) is not None
    assert already_ingested(tmp_path, "owner", DOC_ID) is not None


def test_a_malformed_doc_id_is_rejected_before_anything_is_touched(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)
    client = FakeClient()

    assert delete_document(client, COLLECTION, tmp_path, "t", "../../etc/passwd") is False
    assert client.deletes == []


def test_deleting_a_source_with_no_stored_file_still_removes_its_chunks(tmp_path, monkeypatch):
    """URLs and non-PDF uploads have chunks and a manifest entry, but no file."""
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)
    record_ingestion(tmp_path, "t", DOC_ID, source="https://x.test", source_type="web", chunks=2)
    client = FakeClient()

    assert delete_document(client, COLLECTION, tmp_path, "t", DOC_ID) is True

    assert client.deletes == [(COLLECTION, "t")]
    assert already_ingested(tmp_path, "t", DOC_ID) is None
