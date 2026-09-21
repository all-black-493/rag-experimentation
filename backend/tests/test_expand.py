from langchain_core.documents import Document
from weaviate.classes.query import HybridFusion

from app.graph.edges import edges_for_chunk
from app.graph.refs import extract_references
from app.graph.resolve import IndexedDocument, Resolver
from app.graph.store import Graph
from app.retrieval import expand as expand_module
from app.retrieval.expand import expand, looks_relational, lookups_for
from app.retrieval.filters import LegalFilters
from app.retrieval.plan import QueryPlan, SubQuery

LILYA = IndexedDocument(
    "d-lilya",
    "case_law",
    "Republic v Lilya (Sexual Offence E105 of 2021) [2025] KEMC 179 (KLR)",
    "u-lilya",
)
SOA = IndexedDocument("d-soa", "legislation", "Sexual Offences Act", "u-soa")


def graph_with_lilya():
    resolver = Resolver([LILYA, SOA])
    refs = extract_references(
        "Kaingu Elias Kasono v Republic Criminal Appeal No. 54 of 2010; section 8 of the Sexual Offences Act"
    )
    g = Graph()
    for e in edges_for_chunk(LILYA, 24, refs, resolver):
        g.add(e.properties())
    return g


class FakeEmbeddings:
    def embed_query(self, text):
        return [0.0]


def chunk(doc_id, index, url, collection="case_law"):
    return Document(
        f"{url}#{index}",
        metadata={"doc_id": doc_id, "url": url, "chunk_index": index, "collection": collection},
    )


def test_relational_wording_is_detected_without_a_model():
    assert looks_relational("Which cases have applied Kaingu Elias Kasono v Republic?")
    assert looks_relational("What judgments cite section 8 of the Sexual Offences Act?")
    assert not looks_relational("What is the penalty for defilement?")
    # Mentions citing, but asks about one judgment.
    assert not looks_relational(
        "In Republic v Oundo, what did counsel argue, citing Republic v Danson Mgunya?"
    )


def test_lookups_find_citing_passages_for_a_named_authority():
    found = lookups_for("Which judgments cite Kaingu Elias Kasono v Republic?", graph_with_lilya())
    assert [(cited, [n.via_chunk_index for n in ns]) for cited, ns in found] == [
        ("Kaingu Elias Kasono v Republic", [24])
    ]


def test_lookups_fall_back_from_a_section_to_the_act():
    found = lookups_for("cases applying section 11 of the Sexual Offences Act", graph_with_lilya())
    assert found and found[0][1][0].via_doc_id == "d-lilya"


def test_expand_adds_the_citing_chunk_tagged_with_why(monkeypatch):
    monkeypatch.setattr(
        expand_module,
        "fetch_chunk",
        lambda client, coll, doc_id, idx: chunk(doc_id, idx, f"u-{doc_id}"),
    )
    state = {
        "question": "Which cases cite Kaingu Elias Kasono v Republic?",
        "mode": "search",
        "user_filters": LegalFilters(),
        "plan": QueryPlan(sub_queries=[SubQuery(query="q", collection="case_law")], rationale="r"),
        "documents": [chunk("d-other", 0, "u-other")],
    }

    result = expand(
        state,
        client=object(),
        embeddings=FakeEmbeddings(),
        graph=graph_with_lilya(),
        alpha=0.5,
        fusion=HybridFusion.RELATIVE_SCORE,
        max_lookup_passages=12,
        max_neighbours=8,
        budget=40,
    )

    added = [d for d in result["documents"] if d.metadata.get("via")]
    assert [
        (d.metadata["doc_id"], d.metadata["chunk_index"], d.metadata["via"]) for d in added
    ] == [("d-lilya", 24, "cites Kaingu Elias Kasono v Republic")]
    assert result["expansion"]["added"] == 1
    assert result["documents"][0].metadata["doc_id"] == "d-other"  # originals keep their place


def test_expand_keeps_to_the_users_restrictions(monkeypatch):
    def fetch(client, coll, doc_id, idx):
        doc = chunk(doc_id, idx, f"u-{doc_id}")
        doc.metadata.update({"court_code": "kemc", "year": 2024})
        return doc

    monkeypatch.setattr(expand_module, "fetch_chunk", fetch)

    def run(user):
        state = {
            "question": "Which cases cite Kaingu Elias Kasono v Republic?",
            "mode": "search",
            "user_filters": user,
            "plan": QueryPlan(sub_queries=[SubQuery(query="q", collection="case_law")], rationale="r"),
            "documents": [],
        }
        return expand(
            state,
            client=object(),
            embeddings=FakeEmbeddings(),
            graph=graph_with_lilya(),
            alpha=0.5,
            fusion=HybridFusion.RELATIVE_SCORE,
            max_lookup_passages=12,
            max_neighbours=8,
            budget=40,
        )["expansion"]["added"]

    assert run(LegalFilters()) == 1
    assert run(LegalFilters(courts=("kemc",), year_from=2024)) == 1
    # Legislation only, another court, later years: the citing judgment is out of scope.
    assert run(LegalFilters(collections=("legislation",))) == 0
    assert run(LegalFilters(courts=("kehc",))) == 0
    assert run(LegalFilters(year_from=2025)) == 0


def test_expand_displaces_the_weakest_candidates_at_the_budget(monkeypatch):
    monkeypatch.setattr(
        expand_module,
        "fetch_chunk",
        lambda client, coll, doc_id, idx: chunk(doc_id, idx, f"u-{doc_id}"),
    )
    originals = []
    for i, score in enumerate([0.9, 0.2, 0.5]):
        doc = chunk(f"d-{i}", 0, f"u-{i}")
        doc.metadata["hybrid_score"] = score
        originals.append(doc)
    state = {
        "question": "Which cases cite Kaingu Elias Kasono v Republic?",
        "mode": "search",
        "user_filters": LegalFilters(),
        "plan": QueryPlan(sub_queries=[SubQuery(query="q", collection="case_law")], rationale="r"),
        "documents": originals,
    }

    result = expand(
        state,
        client=object(),
        embeddings=FakeEmbeddings(),
        graph=graph_with_lilya(),
        alpha=0.5,
        fusion=HybridFusion.RELATIVE_SCORE,
        max_lookup_passages=12,
        max_neighbours=8,
        budget=3,
    )

    # One passage added, so the lowest-scored original goes; order is otherwise kept.
    assert [d.metadata["doc_id"] for d in result["documents"]] == ["d-0", "d-2", "d-lilya"]


def test_expand_is_a_no_op_for_an_ordinary_question(monkeypatch):
    monkeypatch.setattr(
        expand_module, "fetch_chunk", lambda *a: (_ for _ in ()).throw(AssertionError("no fetch"))
    )
    state = {
        "question": "What is the penalty for defilement?",
        "mode": "ask",
        "user_filters": LegalFilters(),
        "plan": QueryPlan(sub_queries=[SubQuery(query="q", collection="case_law")], rationale="r"),
        "documents": [chunk("d-other", 0, "u-other")],
    }

    result = expand(
        state,
        client=object(),
        embeddings=FakeEmbeddings(),
        graph=graph_with_lilya(),
        alpha=0.5,
        fusion=HybridFusion.RELATIVE_SCORE,
        max_lookup_passages=12,
        max_neighbours=8,
        budget=40,
    )

    assert len(result["documents"]) == 1
    assert result["expansion"] == {"lookups": [], "neighbours": 0, "added": 0}
