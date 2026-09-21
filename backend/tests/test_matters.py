"""Matters: the store, parsing, scope, and the ingest job end to end (fakes for Weaviate)."""

import io
from pathlib import Path

import pymupdf
import pytest
from langchain_core.documents import Document

from app.config import Settings
from app.matters import ingest as ingest_module
from app.matters.catalog import describe_matter
from app.matters.chunking import chunk_file
from app.matters.loaders import UploadError, validate
from app.matters.models import DocumentProfile, MatterDocument
from app.matters.pdf import chunk_pdf, extract_blocks, pack_blocks
from app.matters.store import MatterStore
from app.retrieval.citations import build_citations, label
from app.retrieval.filters import LegalFilters, collections_in_scope


def make_pdf(path: Path, pages: list[str]) -> Path:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def settings() -> Settings:
    return Settings(child_chunk_size_tokens=60, chunk_overlap_tokens=10, parent_window_radius=1)


# --- store -------------------------------------------------------------------


def test_store_round_trips_a_matter_and_its_documents(tmp_path):
    store = MatterStore(tmp_path)
    matter = store.create("  Otieno v Kamau  ")
    assert matter.name == "Otieno v Kamau"
    assert store.get(matter.id).documents == []
    assert [m.id for m in store.list()] == [matter.id]

    document = MatterDocument(doc_id="a" * 40, name="lease.pdf", kind="pdf", bytes=10)
    store.add_document(matter.id, document)
    store.save_file(matter.id, document.doc_id, ".pdf", b"%PDF-1.4 x")
    updated = store.update_document(matter.id, document.doc_id, status="indexed", chunks=3)
    assert updated.status == "indexed" and updated.chunks == 3
    assert store.file_path(matter.id, document.doc_id).read_bytes() == b"%PDF-1.4 x"
    # The same content uploaded again replaces the record instead of doubling it.
    store.add_document(matter.id, document)
    assert len(store.get(matter.id).documents) == 1

    assert store.remove_document(matter.id, document.doc_id)
    assert store.file_path(matter.id, document.doc_id) is None
    assert store.get(matter.id).documents == []


def test_store_refuses_ids_that_are_not_ids(tmp_path):
    store = MatterStore(tmp_path)
    assert store.get("../etc") is None
    assert store.file_path("0" * 12, "../../secret") is None
    # A malformed id is simply no matter; nothing on disk is touched to find out.
    with pytest.raises(KeyError):
        store.add_document(
            "not-an-id", MatterDocument(doc_id="a" * 40, name="x", kind="text", bytes=1)
        )


# --- parsing -----------------------------------------------------------------


def test_upload_validation_catches_the_gross_mistakes():
    assert validate("brief.pdf", b"%PDF-1.7 ...", 1024) == "pdf"
    assert validate("notes.md", b"# Notes", 1024) == "text"
    with pytest.raises(UploadError, match="Unsupported"):
        validate("deck.pptx", b"PK\x03\x04", 1024)
    with pytest.raises(UploadError, match="empty"):
        validate("brief.pdf", b"", 1024)
    with pytest.raises(UploadError, match="limit"):
        validate("brief.pdf", b"%PDF-" + b"x" * 2000, 1024)
    with pytest.raises(UploadError, match="look like"):
        validate("brief.pdf", b"hello", 1024)
    with pytest.raises(UploadError, match="UTF-8"):
        validate("notes.txt", b"\xff\xfe", 1024)


def test_pdf_chunks_keep_their_page_and_box(tmp_path):
    path = make_pdf(
        tmp_path / "lease.pdf",
        ["Clause 1. The tenant shall pay rent monthly.", "Clause 9. Notice is thirty days."],
    )
    blocks = extract_blocks(path)
    assert [b["page"] for b in blocks] == [1, 2]
    assert blocks[0]["bbox"][0] >= 72 - 1 and blocks[0]["page_width"] > 0

    chunks = chunk_pdf(path, settings())
    assert [c.metadata["page"] for c in chunks] == [1, 2]
    assert "thirty days" in chunks[1].page_content
    assert chunks[1].metadata["parent_text"] == chunks[1].page_content
    assert len(chunks[1].metadata["bbox"]) == 4


def test_packing_never_crosses_a_page_and_carries_a_small_block_as_overlap():
    def block(text, page):
        return {"text": text, "page": page, "bbox": [0, 0, 1, 1], "page_width": 1, "page_height": 1}

    blocks = [
        block("one two three", 1),
        block("four", 1),
        block("five six seven eight", 1),
        block("nine", 2),
    ]
    chunks = pack_blocks(blocks, chunk_tokens=5, overlap_tokens=2)
    assert [c["page"] for c in chunks] == [1, 1, 2]
    # "four" fit the overlap budget, so it opens the next chunk on the same page.
    assert chunks[1]["text"].startswith("four")
    assert chunks[2]["text"] == "nine"


def test_text_documents_go_through_the_corpus_splitter(tmp_path):
    path = tmp_path / "letter.txt"
    path.write_text(
        "Dear Sir,\n\nWe demand payment of KSh 400,000 within 14 days.\n\nYours faithfully"
    )
    chunks = chunk_file(
        path, "text", settings(), matter_id="0" * 12, doc_id="b" * 40, name="letter.txt"
    )
    assert chunks and chunks[0].metadata["collection"] == "matter"
    assert chunks[0].metadata["url"] == f"/matters/{'0' * 12}/files/{'b' * 40}"
    assert "page" not in chunks[0].metadata


# --- scope and citations ---------------------------------------------------


def test_matter_is_in_scope_only_when_named():
    assert collections_in_scope(LegalFilters()) == ("legislation", "case_law")
    assert collections_in_scope(LegalFilters(matter_id="0" * 12)) == (
        "legislation",
        "case_law",
        "matter",
    )
    # Ticked explicitly without a matter: nothing to search there.
    assert collections_in_scope(LegalFilters(collections=("matter", "legislation"))) == (
        "legislation",
    )
    assert LegalFilters(collections=("matter",), matter_id="0" * 12).allows("matter")
    assert not LegalFilters().allows("matter")


def test_a_matter_passage_is_labelled_as_the_users_own_document():
    doc = Document(
        "Clause 9. Notice is thirty days.",
        metadata={
            "collection": "matter",
            "matter_id": "0" * 12,
            "doc_id": "a" * 40,
            "title": "lease.pdf",
            "url": "/matters/000000000000/files/" + "a" * 40,
            "page": 2,
            "bbox": [72.0, 72.0, 300.0, 84.0],
            "page_width": 595.0,
            "page_height": 842.0,
            "chunk_index": 1,
        },
    )
    assert label(doc) == "lease.pdf — the user's own document, page 2"
    citation = build_citations([doc])[0]
    assert citation["page"] == 2 and citation["bbox"] == [72.0, 72.0, 300.0, 84.0]
    assert citation["matter_id"] == "0" * 12


def test_planner_catalog_lists_the_matters_documents():
    store_doc = MatterDocument(
        doc_id="a" * 40,
        name="lease.pdf",
        kind="pdf",
        bytes=1,
        status="indexed",
        profile=DocumentProfile(
            summary="A five-year lease of shop 4.",
            document_type="contract",
            parties=["Otieno", "Kamau"],
        ),
    )
    pending = MatterDocument(doc_id="b" * 40, name="plaint.pdf", kind="pdf", bytes=1)
    from app.matters.models import Matter

    text = describe_matter(
        Matter(id="0" * 12, name="Otieno v Kamau", documents=[store_doc, pending])
    )
    assert '"Otieno v Kamau" (1 documents)' in text
    assert "lease.pdf — contract: A five-year lease of shop 4. Parties: Otieno, Kamau." in text
    assert "plaint.pdf" not in text  # not indexed yet


# --- the job ---------------------------------------------------------------


class FakeTenantData:
    def __init__(self):
        self.deleted = []
        self.inserted = []

    def delete_many(self, where):
        self.deleted.append(where)

    def insert_many(self, batch):
        self.inserted.extend(batch)

        class Result:
            has_errors = False

        return Result()


class FakeClient:
    def __init__(self):
        self.data = FakeTenantData()
        self.tenants_used = []
        self.tenants_created = []

    @property
    def collections(self):
        return self

    @property
    def tenants(self):
        return self

    def exists(self, tenant):
        return tenant in self.tenants_created

    def create(self, tenants):
        self.tenants_created.extend(t.name for t in tenants)

    def use(self, name):
        assert name == "MatterDocument"
        return self

    def with_tenant(self, tenant):
        self.tenants_used.append(tenant)
        return self


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[0.1, 0.2] for _ in texts]


class FailingProfiler:
    def with_structured_output(self, schema):
        raise RuntimeError("401 invalid api key")


def test_ingest_indexes_then_profiles_and_survives_a_profile_failure(tmp_path, monkeypatch):
    store = MatterStore(tmp_path)
    matter = store.create("Otieno v Kamau")
    path = make_pdf(tmp_path / "src.pdf", ["Clause 1. Rent.", "Clause 9. Notice is thirty days."])
    content = path.read_bytes()
    doc_id = "c" * 40
    store.save_file(matter.id, doc_id, ".pdf", content)
    store.add_document(
        matter.id, MatterDocument(doc_id=doc_id, name="lease.pdf", kind="pdf", bytes=len(content))
    )
    client = FakeClient()

    indexed = ingest_module.ingest(
        store, client, FakeEmbeddings(), settings(), FailingProfiler(), matter.id, doc_id
    )

    assert indexed == 2
    assert client.tenants_created == [matter.id]
    assert client.tenants_used[0] == matter.id
    assert len(client.data.inserted) == 2
    assert client.data.inserted[1].properties["page"] == 2
    record = store.get(matter.id).document(doc_id)
    assert record.status == "indexed" and record.chunks == 2 and record.pages == 2
    # Searchable regardless; the missing profile says why, and so does the missing tree.
    assert record.profile is None and "401" in record.profile_error
    assert store.get(matter.id).topics == 0 and store.get(matter.id).topics_error


def test_ingest_marks_a_document_failed_when_nothing_can_be_read(tmp_path):
    store = MatterStore(tmp_path)
    matter = store.create("m")
    doc_id = "d" * 40
    store.save_file(matter.id, doc_id, ".txt", b"   \n  ")
    store.add_document(
        matter.id, MatterDocument(doc_id=doc_id, name="blank.txt", kind="text", bytes=6)
    )

    with pytest.raises(ValueError, match="no text"):
        ingest_module.ingest(
            store, FakeClient(), FakeEmbeddings(), settings(), None, matter.id, doc_id
        )
    record = store.get(matter.id).document(doc_id)
    assert record.status == "failed" and "no text" in record.error


@pytest.mark.anyio
async def test_job_registry_runs_work_and_reports_failures():
    from app.jobs import JobRegistry

    registry = JobRegistry(max_concurrency=1)
    finished = []
    good = registry.submit("m", "a", lambda: 3, on_finish=lambda: finished.append("a"))
    bad = registry.submit("m", "b", lambda: 1 / 0)
    for task in list(registry._tasks):
        await task
    assert (good.status, good.result) == ("succeeded", 3)
    assert bad.status == "failed" and "division" in bad.error
    assert finished == ["a"]
    # Scoped: another matter can't read this one's job.
    assert registry.get(good.id, "other") is None


def test_uploads_are_content_addressed():
    from app.corpus.ids import content_id

    assert content_id(b"same bytes") == content_id(b"same bytes")
    assert len(content_id(io.BytesIO(b"x").getvalue())) == 40


def test_the_relevance_floor_does_not_apply_to_the_users_own_documents():
    from app.retrieval.rerank import _passes

    corpus = Document("x", metadata={"collection": "case_law", "relevance_score": -0.3})
    own = Document("x", metadata={"collection": "matter", "relevance_score": -0.3})
    assert not _passes(corpus, 0.2)
    assert _passes(own, 0.2)
