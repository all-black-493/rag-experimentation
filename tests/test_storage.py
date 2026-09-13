from app.storage import get_pdf_path, save_pdf

VALID_DOC_ID = "12345678-1234-1234-1234-123456789012"


def test_save_and_get_pdf_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)

    save_pdf("tenant-a", VALID_DOC_ID, b"%PDF-1.4 fake content")

    path = get_pdf_path("tenant-a", VALID_DOC_ID)
    assert path is not None
    assert path.read_bytes() == b"%PDF-1.4 fake content"


def test_get_pdf_path_is_scoped_to_tenant(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)

    save_pdf("tenant-a", VALID_DOC_ID, b"content")

    assert get_pdf_path("tenant-b", VALID_DOC_ID) is None


def test_get_pdf_path_rejects_malformed_doc_id(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)

    assert get_pdf_path("tenant-a", "../../etc/passwd") is None
    assert get_pdf_path("tenant-a", "not-a-uuid") is None


def test_get_pdf_path_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.UPLOADS_DIR", tmp_path)

    assert get_pdf_path("tenant-a", VALID_DOC_ID) is None
