import pytest

from app.ingestion.validation import UploadValidationError, validate_upload

_ONE_MB = 1024 * 1024


def test_validate_upload_accepts_real_pdf():
    validate_upload("doc.pdf", b"%PDF-1.7\n...rest of a real pdf...", _ONE_MB)


def test_validate_upload_rejects_fake_pdf_extension():
    with pytest.raises(UploadValidationError, match="valid .pdf"):
        validate_upload("doc.pdf", b"this is not actually a pdf", _ONE_MB)


def test_validate_upload_accepts_utf8_text():
    validate_upload("notes.md", "hello, world — café".encode(), _ONE_MB)


def test_validate_upload_rejects_non_utf8_text():
    with pytest.raises(UploadValidationError, match="UTF-8"):
        validate_upload("notes.md", b"\xff\xfe not valid utf-8", _ONE_MB)


def test_validate_upload_rejects_empty_file():
    with pytest.raises(UploadValidationError, match="empty"):
        validate_upload("doc.pdf", b"", _ONE_MB)


def test_validate_upload_rejects_oversized_file():
    with pytest.raises(UploadValidationError, match="exceeds"):
        validate_upload("doc.pdf", b"%PDF-" + b"x" * _ONE_MB, _ONE_MB)
