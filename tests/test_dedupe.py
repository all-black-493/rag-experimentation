import uuid

import pytest

from app.ingestion.dedupe import (
    already_ingested,
    content_id,
    forget_ingestion,
    list_ingested,
    record_ingestion,
)
from app.storage import DOC_ID_PATTERN


def test_identical_bytes_get_the_same_id():
    assert content_id(b"hello") == content_id(b"hello")
    assert content_id(b"hello") != content_id(b"hello ")


def test_ids_cannot_be_read_as_uuids():
    """A uuid-shaped id gets stored as Weaviate's native `uuid` type and comes back
    dashed, so a citation would carry an id the file was never stored under."""
    with pytest.raises(ValueError):
        uuid.UUID(content_id(b"hello"))


def test_ids_match_the_pattern_that_guards_stored_paths():
    assert DOC_ID_PATTERN.match(content_id(b"hello"))


def test_unrecorded_content_is_not_reported_as_ingested(tmp_path):
    assert already_ingested(tmp_path, "tenant", content_id(b"x")) is None


def test_recorded_content_is_recognised(tmp_path):
    doc_id = content_id(b"x")
    record_ingestion(tmp_path, "tenant", doc_id, source="a.pdf", source_type="pdf", chunks=3)

    previous = already_ingested(tmp_path, "tenant", doc_id)

    assert previous == {"source": "a.pdf", "source_type": "pdf", "chunks": 3}


def test_manifests_are_isolated_per_tenant(tmp_path):
    """One session's upload must not make another's look already-ingested."""
    doc_id = content_id(b"shared")
    record_ingestion(tmp_path, "tenant-a", doc_id, source="a.pdf", source_type="pdf", chunks=1)

    assert already_ingested(tmp_path, "tenant-b", doc_id) is None


def test_a_corrupt_manifest_falls_back_to_re_ingesting(tmp_path):
    """Wasteful but correct; refusing the upload would be worse."""
    (tmp_path / "tenant").mkdir()
    (tmp_path / "tenant" / "ingested.json").write_text("{truncated")

    assert already_ingested(tmp_path, "tenant", content_id(b"x")) is None


def test_recording_preserves_earlier_entries(tmp_path):
    record_ingestion(tmp_path, "t", "id-one", source="one.pdf", source_type="pdf", chunks=1)
    record_ingestion(tmp_path, "t", "id-two", source="two.pdf", source_type="pdf", chunks=2)

    assert already_ingested(tmp_path, "t", "id-one") is not None
    assert already_ingested(tmp_path, "t", "id-two") is not None


def test_listing_returns_most_recent_first(tmp_path):
    record_ingestion(tmp_path, "t", "id-one", source="one.pdf", source_type="pdf", chunks=1)
    record_ingestion(tmp_path, "t", "id-two", source="two.pdf", source_type="pdf", chunks=2)

    listed = list_ingested(tmp_path, "t")

    assert [entry["doc_id"] for entry in listed] == ["id-two", "id-one"]
    assert listed[0] == {"doc_id": "id-two", "source": "two.pdf", "source_type": "pdf", "chunks": 2}


def test_listing_is_empty_for_a_tenant_that_has_ingested_nothing(tmp_path):
    assert list_ingested(tmp_path, "t") == []


def test_forgetting_lets_the_same_content_be_ingested_again(tmp_path):
    """Without this, a deleted document could never be re-added: the id is the
    content's hash, so the re-upload would hit the dedupe check and be skipped."""
    doc_id = content_id(b"x")
    record_ingestion(tmp_path, "t", doc_id, source="a.pdf", source_type="pdf", chunks=3)

    assert forget_ingestion(tmp_path, "t", doc_id) is True
    assert already_ingested(tmp_path, "t", doc_id) is None


def test_forgetting_leaves_other_documents_alone(tmp_path):
    record_ingestion(tmp_path, "t", "id-one", source="one.pdf", source_type="pdf", chunks=1)
    record_ingestion(tmp_path, "t", "id-two", source="two.pdf", source_type="pdf", chunks=2)

    forget_ingestion(tmp_path, "t", "id-one")

    assert already_ingested(tmp_path, "t", "id-two") is not None


def test_forgetting_an_unknown_document_reports_nothing_was_removed(tmp_path):
    assert forget_ingestion(tmp_path, "t", "missing") is False
