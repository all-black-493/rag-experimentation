from datetime import UTC, datetime

from langchain_core.documents import Document

from app.retrieval.citations import build_citations, format_context, label


def judgment(text="held...", **overrides) -> Document:
    metadata = {
        "collection": "case_law",
        "title": "Republic v Chumba [2025] KEMC 94 (KLR)",
        "url": "https://new.kenyalaw.org/akn/ke/judgment/kemc/2025/94/eng@2025-05-15",
        "court": "Magistrates' Courts",
        "court_code": "kemc",
        "decision_date": datetime(2025, 5, 15, tzinfo=UTC),
        "year": 2025,
        "chunk_index": 3,
        "parent_text": "before held... after",
        **overrides,
    }
    return Document(page_content=text, metadata=metadata)


def act(text="provides...") -> Document:
    return Document(
        page_content=text,
        metadata={
            "collection": "legislation",
            "title": "Traffic Act",
            "url": "https://new.kenyalaw.org/akn/ke/act/1953/39/eng@2022-12-31",
            "year": 1953,
            "chunk_index": 12,
        },
    )


def test_judgment_label_names_court_and_date():
    assert label(judgment()) == "Republic v Chumba [2025] KEMC 94 (KLR) — Magistrates' Courts, 2025-05-15"


def test_act_label_is_its_title():
    assert label(act()) == "Traffic Act"


def test_format_context_numbers_passages_and_uses_parent_windows():
    context = format_context([judgment(), act()])

    assert context.startswith("[1] (Republic v Chumba")
    assert "before held... after" in context
    assert "[2] (Traffic Act)\nprovides..." in context


def test_citations_come_from_metadata_and_dates_are_iso_strings():
    citation = build_citations([judgment()])[0]

    assert citation["index"] == 1
    assert citation["collection"] == "case_law"
    assert citation["court_code"] == "kemc"
    # Weaviate returns date properties as datetimes; the API speaks ISO dates.
    assert citation["decision_date"] == "2025-05-15"
    assert citation["chunk_index"] == 3
    assert citation["text"] == "held..."
    assert citation["parent_text"] == "before held... after"


def test_act_citation_has_no_court_fields():
    citation = build_citations([act()])[0]

    assert citation["court"] is None
    assert citation["decision_date"] is None
    assert citation["parent_text"] == "provides..."


def test_citations_ignore_anything_the_model_might_say():
    """The list is built purely from retrieved metadata; there is no answer input."""
    citations = build_citations([judgment(), act()])

    assert [c["index"] for c in citations] == [1, 2]
    assert [c["title"] for c in citations] == ["Republic v Chumba [2025] KEMC 94 (KLR)", "Traffic Act"]
