from app.ingestion.dedupe import content_id
from app.storage import (
    delete_document_files,
    get_page_thumbnail_path,
    get_pdf_path,
    save_page_thumbnail,
    save_pdf,
)

# Derived from content_id rather than written out by hand: the two have to agree
# on the id's shape, and a literal here would let them drift apart - which is
# exactly how every stored PDF once became unservable.
DOC_ID = content_id(b"%PDF-1.4 fake content")


def test_save_and_get_pdf_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)

    save_pdf("tenant-a", DOC_ID, b"%PDF-1.4 fake content")

    path = get_pdf_path("tenant-a", DOC_ID)
    assert path is not None
    assert path.read_bytes() == b"%PDF-1.4 fake content"


def test_get_pdf_path_is_scoped_to_tenant(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)

    save_pdf("tenant-a", DOC_ID, b"content")

    assert get_pdf_path("tenant-b", DOC_ID) is None


def test_get_pdf_path_rejects_malformed_doc_id(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)

    assert get_pdf_path("tenant-a", "../../etc/passwd") is None
    assert get_pdf_path("tenant-a", "not-a-content-id") is None


def test_get_pdf_path_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)

    assert get_pdf_path("tenant-a", DOC_ID) is None


def test_delete_removes_the_pdf_and_every_page_thumbnail(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)
    save_pdf("tenant-a", DOC_ID, b"content")
    save_page_thumbnail("tenant-a", DOC_ID, 1, b"png-one")
    save_page_thumbnail("tenant-a", DOC_ID, 7, b"png-seven")

    assert delete_document_files("tenant-a", DOC_ID) == 3

    assert get_pdf_path("tenant-a", DOC_ID) is None
    assert get_page_thumbnail_path("tenant-a", DOC_ID, 1) is None
    assert get_page_thumbnail_path("tenant-a", DOC_ID, 7) is None


def test_delete_leaves_another_tenants_copy_alone(tmp_path, monkeypatch):
    """Two sessions can upload the same bytes; one deleting must not blank the other."""
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)
    save_pdf("tenant-a", DOC_ID, b"content")
    save_pdf("tenant-b", DOC_ID, b"content")

    delete_document_files("tenant-a", DOC_ID)

    assert get_pdf_path("tenant-b", DOC_ID) is not None


def test_delete_is_a_no_op_for_a_source_with_no_stored_file(tmp_path, monkeypatch):
    """Only PDFs are persisted; deleting a .docx or a URL has no file to remove."""
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)
    (tmp_path / "tenant-a").mkdir()

    assert delete_document_files("tenant-a", DOC_ID) == 0


def test_delete_rejects_a_malformed_doc_id(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)

    assert delete_document_files("tenant-a", "../../etc") == 0
