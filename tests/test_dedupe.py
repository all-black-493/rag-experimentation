from app.ingestion.dedupe import already_ingested, content_id, record_ingestion


def test_identical_bytes_get_the_same_id():
    assert content_id(b"hello") == content_id(b"hello")
    assert content_id(b"hello") != content_id(b"hello ")


def test_unrecorded_content_is_not_reported_as_ingested(tmp_path):
    assert already_ingested(tmp_path, "tenant", content_id(b"x")) is None


def test_recorded_content_is_recognised(tmp_path):
    doc_id = content_id(b"x")
    record_ingestion(tmp_path, "tenant", doc_id, source="a.pdf", chunks=3)

    previous = already_ingested(tmp_path, "tenant", doc_id)

    assert previous == {"source": "a.pdf", "chunks": 3}


def test_manifests_are_isolated_per_tenant(tmp_path):
    """One session's upload must not make another's look already-ingested."""
    doc_id = content_id(b"shared")
    record_ingestion(tmp_path, "tenant-a", doc_id, source="a.pdf", chunks=1)

    assert already_ingested(tmp_path, "tenant-b", doc_id) is None


def test_a_corrupt_manifest_falls_back_to_re_ingesting(tmp_path):
    """Wasteful but correct; refusing the upload would be worse."""
    (tmp_path / "tenant").mkdir()
    (tmp_path / "tenant" / "ingested.json").write_text("{truncated")

    assert already_ingested(tmp_path, "tenant", content_id(b"x")) is None


def test_recording_preserves_earlier_entries(tmp_path):
    record_ingestion(tmp_path, "t", "id-one", source="one.pdf", chunks=1)
    record_ingestion(tmp_path, "t", "id-two", source="two.pdf", chunks=2)

    assert already_ingested(tmp_path, "t", "id-one") is not None
    assert already_ingested(tmp_path, "t", "id-two") is not None
