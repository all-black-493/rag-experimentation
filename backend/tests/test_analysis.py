"""Case analysis: the deterministic core, the anchoring, and the run with a failing model."""

import asyncio
from datetime import date

from langchain_core.documents import Document

from app.analysis.chronology import order_events, parse_date
from app.analysis.extract import DocumentExtraction, anchored, page_marked
from app.analysis.models import Event
from app.analysis.run import analyse
from app.analysis.sources import SourceBook, best_passage
from app.graph.refs import extract_references
from app.graph.resolve import IndexedDocument
from app.graph.store import Graph
from app.jobs import JobRegistry
from app.matters.models import MatterDocument
from app.matters.store import MatterStore
from app.workflows import case_analysis
from app.workflows.runs import WorkflowRuns


def chunk(doc_id, index, text, page=1, name="lease.pdf") -> Document:
    return Document(
        text,
        metadata={
            "collection": "matter",
            "matter_id": "0" * 12,
            "doc_id": doc_id,
            "title": name,
            "url": f"/matters/{'0' * 12}/files/{doc_id}",
            "chunk_index": index,
            "page": page,
            "bbox": [10.0, 10.0, 100.0, 20.0],
            "page_width": 595.0,
            "page_height": 842.0,
            "parent_text": text,
        },
    )


LEASE = "a" * 40
LETTER = "b" * 40
CHUNKS = {
    LEASE: [
        chunk(
            LEASE,
            0,
            "THIS LEASE is made on the 3rd day of February 2024 between Wanjiru Karanja and Otieno & Sons Hardware Limited, a company incorporated under the Companies Act, 2015.",
        ),
        chunk(LEASE, 1, "3.1 The Tenant shall pay rent of KSh 120,000 per month.", page=1),
        chunk(
            LEASE,
            2,
            "7.1 If the rent is in arrears for twenty-one days the Landlord may re-enter.",
            page=2,
        ),
    ],
    LETTER: [
        chunk(
            LETTER,
            0,
            "12th August 2025. Our client will levy distress for the rent in arrears under the Distress for Rent Act, and rely on section 26 of the Civil Procedure Act.",
            name="demand-letter.pdf",
        ),
    ],
}


def test_bare_act_names_are_taken_only_on_request():
    text = "levy distress under the Distress for Rent Act and section 26 of the Civil Procedure Act"
    assert [r.key for r in extract_references(text)] == ["Civil Procedure Act"]
    assert [r.key for r in extract_references(text, bare_acts=True)] == [
        "Civil Procedure Act",
        "Distress for Rent Act",
    ]


def test_dates_as_documents_write_them():
    assert parse_date("on the 3rd day of February 2024") == date(2024, 2, 3)
    assert parse_date("18th April 2025") == date(2025, 4, 18)
    assert parse_date("April 25, 2025") == date(2025, 4, 25)
    assert parse_date("since about April 2025") == date(2025, 4, 1)
    assert parse_date("paid on 2025-08-05") == date(2025, 8, 5)
    assert parse_date("no date here") is None
    assert parse_date("31st February 2025") == date(2025, 2, 1)  # the month survives a bad day


def test_chronology_orders_dated_events_and_keeps_the_undated_last():
    events = [
        Event(when="some time later", description="locks changed"),
        Event(when="12th August 2025", description="demand letter"),
        Event(when="18th April 2025", description="roof leaked"),
    ]
    ordered = order_events(events)
    assert [e.description for e in ordered] == ["roof leaked", "demand letter", "locks changed"]
    assert ordered[0].date == "2025-04-18" and ordered[-1].date is None


def test_statements_are_anchored_to_the_passage_they_were_read_from():
    book = SourceBook()
    extraction = DocumentExtraction(
        parties=[{"name": "Otieno & Sons Hardware Limited", "role": "tenant", "page": 1}],
        facts=[{"statement": "Rent is KSh 120,000 per month.", "page": 1}],
        events=[{"when": "3rd day of February 2024", "description": "lease made", "page": 1}],
        issues=["Is the landlord entitled to re-enter?"],
    )
    parties, facts, events, issues = anchored(extraction, CHUNKS[LEASE], book)
    assert facts[0].source == book.index_of(CHUNKS[LEASE][1])
    assert parties[0].source == book.index_of(CHUNKS[LEASE][0])
    assert events[0].source == parties[0].source
    assert issues[0].question.startswith("Is the landlord")
    citations = book.citations()
    assert citations[0]["page"] == 1 and citations[0]["bbox"] == [10.0, 10.0, 100.0, 20.0]
    assert best_passage("", CHUNKS[LEASE]) is None


def test_page_marks_precede_each_new_page():
    assert page_marked(CHUNKS[LEASE]).count("[p.1]") == 1
    assert "[p.2]\n\n7.1" in page_marked(CHUNKS[LEASE])


class FakeResolver:
    def resolve(self, reference):
        if reference.key == "Distress for Rent Act":
            return IndexedDocument(
                "d-distress", "legislation", "Distress for Rent Act", "u-distress"
            )
        return None


def graph_with_cpa() -> Graph:
    g = Graph()
    for i in range(3):
        g.add(
            {
                "source_doc_id": f"j{i}",
                "source_collection": "case_law",
                "source_title": f"Judgment {i}",
                "source_url": f"u{i}",
                "source_chunk_index": 0,
                "kind": "applies",
                "target_ref": "section 26 of the Civil Procedure Act",
                "target_key": "Civil Procedure Act",
                "provision": "26",
                "target_doc_id": "d-cpa",
                "target_collection": "legislation",
                "target_title": "Civil Procedure Act",
            }
        )
    return g


def test_authorities_are_found_resolved_counted_and_anchored():
    from app.analysis.authorities import find_authorities

    book = SourceBook()
    authorities = find_authorities(CHUNKS, FakeResolver(), graph_with_cpa(), book)
    by_key = {a.key: a for a in authorities}
    assert set(by_key) == {"Companies Act", "Distress for Rent Act", "Civil Procedure Act"}
    assert by_key["Distress for Rent Act"].doc_id == "d-distress"
    assert by_key["Civil Procedure Act"].applied_by == 3
    assert by_key["Companies Act"].doc_id is None
    # Statutes first, the most-applied first.
    assert authorities[0].key == "Civil Procedure Act"
    assert (
        book.citations()[by_key["Distress for Rent Act"].sources[0] - 1]["title"]
        == "demand-letter.pdf"
    )


class FailingModel:
    def with_structured_output(self, schema):
        raise RuntimeError("credit balance is too low")


class FakeClient:
    """Serves the matter's chunks and resolves nothing."""

    def __init__(self, chunks):
        self._chunks = chunks

    @property
    def collections(self):
        return self

    def use(self, name):
        return self

    @property
    def tenants(self):
        return self

    def exists(self, tenant):
        return True

    def with_tenant(self, tenant):
        return self

    def iterator(self, return_properties=None):
        class Obj:
            def __init__(self, doc):
                self.properties = {
                    "text": doc.page_content,
                    **{k: v for k, v in doc.metadata.items() if k != "collection"},
                }

        return [Obj(d) for chunks in self._chunks.values() for d in chunks]

    @property
    def query(self):
        return self

    def bm25(self, query, query_properties=None, limit=None, return_properties=None):
        class Response:
            objects = ()

        return Response()


def matter_with_documents(tmp_path):
    store = MatterStore(tmp_path)
    matter = store.create("Karanja v Otieno")
    for doc_id, name in ((LEASE, "lease.pdf"), (LETTER, "demand-letter.pdf")):
        store.add_document(
            matter.id,
            MatterDocument(doc_id=doc_id, name=name, kind="pdf", bytes=1, status="indexed"),
        )
    return store, matter


def test_analysis_stands_on_its_deterministic_steps_when_the_model_fails(tmp_path):
    store, matter = matter_with_documents(tmp_path)
    steps = []
    analysis = analyse(
        store,
        FakeClient(CHUNKS),
        graph_with_cpa(),
        FailingModel(),
        matter.id,
        emit=lambda e, d: steps.append((e, d)),
    )
    assert {a.key for a in analysis.authorities} == {
        "Companies Act",
        "Distress for Rent Act",
        "Civil Procedure Act",
    }
    assert analysis.facts == [] and analysis.report is None
    assert len(analysis.warnings) == 2
    assert analysis.warnings[0].startswith("lease.pdf, demand-letter.pdf: could not be read (credit balance")
    assert analysis.warnings[-1].startswith("no document could be read")
    assert [
        name for e, d in steps if e == "step" and d["status"] == "done" for name in [d["name"]]
    ] == ["documents", "authorities", "extract", "chronology"]
    assert store.get(matter.id).analysis.authorities[0].key == "Civil Procedure Act"


def test_analysis_without_a_model_skips_the_reading_and_says_so(tmp_path):
    store, matter = matter_with_documents(tmp_path)
    analysis = analyse(store, FakeClient(CHUNKS), Graph(), None, matter.id, emit=lambda e, d: None)
    assert len(analysis.authorities) == 3
    assert any("need a model" in w for w in analysis.warnings)


async def _run(tmp_path):
    store, matter = matter_with_documents(tmp_path)
    runs = WorkflowRuns(JobRegistry(max_concurrency=1))
    run = runs.start(
        case_analysis.NAME,
        matter.name,
        lambda r: case_analysis.run(
            r, store=store, client=FakeClient(CHUNKS), graph=Graph(), llm=None, matter_id=matter.id
        ),
    )
    events = [item async for item in run.follow()]
    for task in list(runs._jobs._tasks):
        await task
    return run, events


def test_the_workflow_reports_steps_then_the_analysis(tmp_path):
    run, events = asyncio.run(_run(tmp_path))
    kinds = [e["event"] for e in events]
    assert kinds[0] == "step" and kinds[-1] == "done"
    assert "authorities" in kinds and "chronology" in kinds
    assert run.job.status == "succeeded"
    assert len(events[-1]["data"]["authorities"]) == 3
