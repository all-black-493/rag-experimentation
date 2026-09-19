"""What one document says: parties, facts, events, issues - one model call per document.

The model reads page-marked text and gives back page numbers; the passage
each item was read from is then found deterministically by word overlap on
that page, so every anchor is a real chunk with a real box, not a guess.
"""

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from app.analysis.models import Event, Fact, Issue, Party
from app.analysis.sources import SourceBook, best_passage
from app.prompts import load_chat_prompt
from app.tracing import linked_prompt, observation

EXTRACT_PROMPT = load_chat_prompt("extract")

# Enough for a long lease; a bundle beyond it is read from its first pages.
_MAX_CHARS = 60_000


class ExtractedParty(BaseModel):
    name: str
    role: str
    page: int | None = None


class ExtractedFact(BaseModel):
    statement: str
    page: int | None = None


class ExtractedEvent(BaseModel):
    when: str = Field(description="The date as written.")
    description: str
    page: int | None = None


class DocumentExtraction(BaseModel):
    parties: list[ExtractedParty] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    events: list[ExtractedEvent] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


def page_marked(chunks: list[Document]) -> str:
    parts = []
    last_page = None
    for chunk in chunks:
        page = chunk.metadata.get("page")
        if page is not None and page != last_page:
            parts.append(f"[p.{page}]")
            last_page = page
        parts.append(chunk.page_content)
    return "\n\n".join(parts)[:_MAX_CHARS]


def extract_document(llm: BaseChatModel, name: str, chunks: list[Document]) -> DocumentExtraction:
    with observation(
        as_type="chain",
        name="extract-document",
        input={"name": name, "chunks": len(chunks)},
        metadata={"prompt": EXTRACT_PROMPT.name, "prompt_version": EXTRACT_PROMPT.version},
    ) as span:
        message = EXTRACT_PROMPT.template.invoke({"name": name, "text": page_marked(chunks)})
        with linked_prompt(EXTRACT_PROMPT.name):
            extraction = llm.with_structured_output(DocumentExtraction).invoke(
                message,
                config={
                    "metadata": {
                        "prompt": EXTRACT_PROMPT.name,
                        "prompt_version": EXTRACT_PROMPT.version,
                    }
                },
            )
        span.update(
            output={
                "parties": len(extraction.parties),
                "facts": len(extraction.facts),
                "events": len(extraction.events),
                "issues": len(extraction.issues),
            }
        )
        return extraction


def anchor(text: str, page: int | None, chunks: list[Document], book: SourceBook) -> int | None:
    """The source number of the passage `text` was read from, on `page` when known."""
    on_page = [c for c in chunks if page is None or c.metadata.get("page") == page]
    passage = best_passage(text, on_page or chunks)
    return book.index_of(passage) if passage is not None else None


def anchored(
    extraction: DocumentExtraction, chunks: list[Document], book: SourceBook
) -> tuple[list[Party], list[Fact], list[Event], list[Issue]]:
    """The extraction with every item pointing at its passage."""
    parties = [
        Party(name=p.name, role=p.role, source=anchor(p.name, p.page, chunks, book))
        for p in extraction.parties
    ]
    facts = [
        Fact(statement=f.statement, source=anchor(f.statement, f.page, chunks, book))
        for f in extraction.facts
    ]
    events = [
        Event(
            when=e.when,
            description=e.description,
            source=anchor(f"{e.when} {e.description}", e.page, chunks, book),
        )
        for e in extraction.events
    ]
    issues = [Issue(question=q) for q in extraction.issues]
    return parties, facts, events, issues
