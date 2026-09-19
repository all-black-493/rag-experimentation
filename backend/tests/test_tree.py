"""The summary tree: clustering, summarising, building, and what a hit hands to retrieval."""

import numpy as np
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.retrieval import topics as topics_module
from app.retrieval.filters import LegalFilters
from app.retrieval.topics import topics
from app.tree.build import Leaf, build_tree
from app.tree.cluster import cluster
from app.tree.store import SummaryNode, leaf_key
from app.tree.summarise import split_title


def test_small_inputs_are_one_cluster_and_larger_ones_split_by_meaning():
    assert cluster(np.zeros((0, 4))) == []
    assert cluster(np.random.default_rng(0).random((6, 4)), target_size=10) == [list(range(6))]
    rng = np.random.default_rng(1)
    a = rng.normal(0, 0.05, (12, 8)) + np.array([1] * 8)
    b = rng.normal(0, 0.05, (12, 8)) + np.array([-1] * 8)
    groups = cluster(np.vstack([a, b]), target_size=12)
    assert sorted(sorted(g) for g in groups) == [list(range(12)), list(range(12, 24))]
    # Deterministic.
    assert cluster(np.vstack([a, b]), target_size=12) == groups


def test_the_title_line_is_split_off_the_summary():
    text = "The passages concern rent arrears under a lease.\nThey cite section 26.\nTitle: Rent arrears and distress"
    assert split_title(text) == (
        "The passages concern rent arrears under a lease. They cite section 26.",
        "Rent arrears and distress",
    )
    assert split_title("No title given at all.") == (
        "No title given at all.",
        "No title given at all.",
    )


class Summariser:
    def __init__(self):
        self.calls = 0

    def invoke(self, message, config=None):
        self.calls += 1
        return AIMessage(content=f"Summary {self.calls}.\nTitle: Topic {self.calls}")


class Embedder:
    def embed_documents(self, texts):
        return [[float(len(t) % 7), 1.0] for t in texts]

    def embed_query(self, text):
        return [0.0, 1.0]


def leaves(n: int, doc_id: str, offset=0.0) -> list[Leaf]:
    rng = np.random.default_rng(3)
    return [
        Leaf(
            leaf_key(doc_id, i),
            doc_id,
            f"passage {i} of {doc_id}",
            list(rng.normal(offset, 0.05, 4)),
        )
        for i in range(n)
    ]


def test_build_tree_summarises_each_cluster_and_points_at_its_leaves():
    summariser = Summariser()
    nodes = build_tree(
        leaves(8, "d1", offset=1.0) + leaves(8, "d2", offset=-1.0),
        summariser,
        Embedder(),
        collection="matter",
        levels=2,
        target_size=8,
    )
    level_one = [n for n in nodes if n.level == 1]
    # One call per cluster; the two documents' passages never share a cluster;
    # every passage sits under exactly one node; level 2 (one node of them all) is not built.
    assert len(level_one) >= 2 and summariser.calls == len(nodes) == len(level_one)
    assert all(len(n.doc_ids) == 1 for n in level_one)
    assert sorted(k for n in level_one for k in n.leaves) == sorted(
        leaf_key(d, i) for d in ("d1", "d2") for i in range(8)
    )
    assert level_one[0].title.startswith("Topic") and level_one[0].vector


def passage(doc_id, index, collection="case_law"):
    return Document(
        f"p{index}",
        metadata={
            "collection": collection,
            "doc_id": doc_id,
            "url": f"u-{doc_id}",
            "chunk_index": index,
            "title": "T",
        },
    )


class FakeLeafClient:
    """Answers fetch_objects by key from a table."""

    def __init__(self, table):
        self.table = table

    @property
    def collections(self):
        return self

    def use(self, name):
        return self

    def with_tenant(self, tenant):
        return self

    @property
    def query(self):
        return self

    def fetch_objects(self, filters=None, limit=1, return_properties=None):
        # The filter is doc_id == X & chunk_index == N; the table is keyed the same way.
        def values(f):
            return (
                [f.value] if hasattr(f, "value") else [v for sub in f.filters for v in values(sub)]
            )

        doc_id, index = values(filters)
        wanted = [(d, i) for (d, i) in self.table if d == doc_id and i == index]

        class Obj:
            def __init__(self, doc):
                self.properties = {
                    "text": doc.page_content,
                    **{k: v for k, v in doc.metadata.items() if k != "collection"},
                }

        class Response:
            objects = tuple(Obj(self.table[k]) for k in wanted[:1])

        return Response()


def test_topics_add_the_leaves_under_a_matching_node_but_never_the_node(monkeypatch):
    node = SummaryNode(
        text="Bail pending trial",
        title="Bail: compelling reasons",
        level=1,
        collection="case_law",
        leaves=[leaf_key("j1", 4), leaf_key("j2", 0)],
        doc_ids=["j1", "j2"],
        score=0.9,
    )
    monkeypatch.setattr(topics_module, "search_summaries", lambda *a, **k: [node])
    table = {("j1", 4): passage("j1", 4), ("j2", 0): passage("j2", 0)}
    state = {
        "question": "compelling reasons to deny bail",
        "user_filters": LegalFilters(),
        "documents": [passage("j2", 0)],
    }
    result = topics(
        state,
        FakeLeafClient(table),
        Embedder(),
        alpha=0.5,
        fusion=None,
        max_nodes=3,
        max_leaves=6,
        budget=40,
    )
    added = [d for d in result["documents"] if d.metadata.get("via")]
    assert [
        (d.metadata["doc_id"], d.metadata["chunk_index"], d.metadata["via"]) for d in added
    ] == [("j1", 4, "topic: Bail: compelling reasons")]
    assert result["topics"] == {
        "nodes": [{"title": "Bail: compelling reasons", "level": 1, "added": 1}],
        "added": 1,
    }
    assert all(d.metadata.get("collection") != "summary" for d in result["documents"])


def test_topics_respect_the_users_collections(monkeypatch):
    node = SummaryNode(
        text="x",
        title="t",
        level=1,
        collection="case_law",
        leaves=[leaf_key("j1", 4)],
        doc_ids=["j1"],
        score=0.9,
    )
    monkeypatch.setattr(topics_module, "search_summaries", lambda *a, **k: [node])
    state = {
        "question": "q",
        "user_filters": LegalFilters(collections=("legislation",)),
        "documents": [],
    }
    result = topics(
        state,
        FakeLeafClient({}),
        Embedder(),
        alpha=0.5,
        fusion=None,
        max_nodes=3,
        max_leaves=6,
        budget=40,
    )
    assert result["topics"]["added"] == 0 and result["documents"] == []
