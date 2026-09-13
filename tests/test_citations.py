import uuid

from langchain_core.documents import Document

from app.retrieval.citations import build_citations, format_context


def test_build_citations_coerces_uuid_doc_id_to_string():
    # Weaviate's autoschema infers doc_id as its native `uuid` type from the
    # value's shape and hands back a uuid.UUID, not a str - the API contract
    # promises `doc_id: str | None`, so build_citations must normalize it.
    doc = Document(
        page_content="chunk text",
        metadata={"source": "doc.pdf", "title": "doc.pdf", "doc_id": uuid.uuid4()},
    )

    citations = build_citations([doc])

    assert isinstance(citations[0]["doc_id"], str)


def test_build_citations_leaves_doc_id_none_for_non_pdf_sources():
    doc = Document(page_content="chunk text", metadata={"source": "notes.md"})

    citations = build_citations([doc])

    assert citations[0]["doc_id"] is None
    assert citations[0]["bbox"] is None


def test_build_citations_ignores_llm_response_entirely():
    # The generation node's LLM response is never passed to build_citations, and
    # never touches Document.metadata. This constructs a citation exactly as the
    # graph does - straight from retrieved Documents - to document that there is
    # no code path by which model output could influence a citation's source,
    # page, doc_id, or any other field. If this ever needs an `answer` or
    # `llm_response` parameter to pass, that invariant has been broken.
    doc = Document(
        page_content="The actual retrieved text.",
        metadata={
            "source": "real_source.pdf",
            "title": "real_source.pdf",
            "source_type": "pdf",
            "page": 3,
            "doc_id": "11111111-1111-1111-1111-111111111111",
        },
    )

    citations = build_citations([doc])

    assert citations[0]["source"] == "real_source.pdf"
    assert citations[0]["page"] == 3
    assert citations[0]["doc_id"] == "11111111-1111-1111-1111-111111111111"


def test_build_citations_defaults_source_type_for_legacy_metadata():
    # Documents ingested before source_type existed (or any metadata gap)
    # degrade to "text" rather than raising or fabricating a PDF/web claim.
    doc = Document(page_content="chunk text", metadata={"source": "notes.md"})

    citations = build_citations([doc])

    assert citations[0]["source_type"] == "text"


def test_format_context_numbers_passages_in_order():
    docs = [
        Document(page_content="first", metadata={"title": "a.md"}),
        Document(page_content="second", metadata={"title": "b.md"}),
    ]

    context = format_context(docs)

    assert context.index("[1]") < context.index("[2]")
    assert "first" in context
    assert "second" in context
