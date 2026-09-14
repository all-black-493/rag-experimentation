from langchain_core.documents import Document

from app.ingestion.parenting import attach_parents, window
from app.retrieval.citations import context_text


def test_window_includes_neighbours_either_side():
    assert window(["a", "b", "c", "d", "e"], 2, 1) == "b\n\nc\n\nd"


def test_window_clamps_at_the_start():
    """The first child has no left neighbour; it must not wrap to the end."""
    assert window(["a", "b", "c"], 0, 1) == "a\n\nb"


def test_window_clamps_at_the_end():
    assert window(["a", "b", "c"], 2, 1) == "b\n\nc"


def test_radius_zero_is_just_the_child():
    assert window(["a", "b", "c"], 1, 0) == "b"


def test_single_child_is_its_own_parent():
    assert window(["only"], 0, 2) == "only"


def test_attach_parents_keeps_child_text_separate():
    """The child is what gets embedded; the parent is only what's read."""
    parented = attach_parents(["a", "b", "c"], radius=1)

    assert [p.text for p in parented] == ["a", "b", "c"]
    assert parented[1].parent_text == "a\n\nb\n\nc"


def test_context_uses_the_parent_window_when_present():
    doc = Document("matched child", metadata={"parent_text": "before\n\nmatched child\n\nafter"})

    assert context_text(doc) == "before\n\nmatched child\n\nafter"


def test_context_falls_back_to_the_chunk_without_a_parent():
    """Documents indexed before small-to-big have no parent_text."""
    assert context_text(Document("just the chunk", metadata={})) == "just the chunk"


def test_empty_parent_text_falls_back_rather_than_blanking_context():
    assert context_text(Document("chunk", metadata={"parent_text": ""})) == "chunk"
