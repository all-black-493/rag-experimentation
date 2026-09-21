"""Read what the first pass found, and say what it missed.

The one thing a single-pass search cannot do is notice its own gaps: the Act
without the cases that applied it, the holding without the proviso, the answer
without the authority against it. This node is that reading - one structured
call over the reranked passages, returning follow-up searches for the next
pass. Bounded: at most `max_follow_ups` per review, at most `max_rounds`
passes in all, and never a search already run.

Research mode only. Ask stays one pass and fast.
"""

import logging

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field, field_validator

from app.metadata import MATTER, Collection
from app.retrieval.citations import label
from app.retrieval.plan import SubQuery
from app.retrieval.prompts import REVIEW_PROMPT
from app.retrieval.state import GraphState
from app.tracing import linked_prompt, observation

logger = logging.getLogger(__name__)

# What the reviewer reads of each passage: enough to know what it covers.
_EXCERPT_CHARS = 400


class FollowUp(BaseModel):
    query: str = Field(description="What to search for, in the corpus's own terms.")
    collection: Collection
    reason: str = Field(description="A few words on what this would fill in or test.")

    @field_validator("query", "reason")
    @classmethod
    def _stripped(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("empty")
        return value


class Review(BaseModel):
    missing: str = Field(
        description="One or two sentences: what the passages found so far do not cover."
    )
    follow_ups: list[FollowUp] = Field(default_factory=list)


def _context(state: GraphState) -> str:
    return "\n\n".join(
        f"[{i}] ({label(doc)})\n{doc.page_content[:_EXCERPT_CHARS]}"
        for i, doc in enumerate(state["documents"], start=1)
    )


def _searched(state: GraphState) -> list[str]:
    return [r["query"] for r in state.get("retrieval", [])]


def review(state: GraphState, llm: BaseChatModel, *, max_follow_ups: int, max_rounds: int) -> dict:
    """Close one pass of retrieval; ask for another only while rounds remain."""
    completed = state.get("rounds", 0) + 1
    if completed >= max_rounds or not state["documents"]:
        return {"rounds": completed, "follow_ups": []}

    user = state["user_filters"]
    searched = _searched(state)
    with observation(
        as_type="chain",
        name="review-pass",
        input={
            "question": state["question"],
            "round": completed,
            "passages": len(state["documents"]),
        },
        metadata={"prompt": REVIEW_PROMPT.name, "prompt_version": REVIEW_PROMPT.version},
    ) as span:
        try:
            message = REVIEW_PROMPT.template.invoke(
                {
                    "question": state["question"],
                    "context": _context(state),
                    "max_follow_ups": max_follow_ups,
                    "searched": "; ".join(searched),
                    "matter_collection": (
                        " and matter (the lawyer's own documents)" if user.matter_id else ""
                    ),
                }
            )
            with linked_prompt(REVIEW_PROMPT.name):
                result = llm.with_structured_output(Review).invoke(
                    message,
                    config={
                        "metadata": {
                            "prompt": REVIEW_PROMPT.name,
                            "prompt_version": REVIEW_PROMPT.version,
                        }
                    },
                )
        except Exception as exc:  # noqa: BLE001 - a review that fails costs a round, not the answer
            logger.warning("review unavailable (%s); writing up what was found", exc)
            span.update(output={"error": str(exc)})
            return {"rounds": completed, "follow_ups": []}

        follow_ups = _admissible(result.follow_ups, user, searched)[:max_follow_ups]
        entry = {
            "round": completed,
            "missing": result.missing,
            "follow_ups": [f.model_dump() for f in follow_ups],
        }
        span.update(output=entry)
        return {
            "rounds": completed,
            "follow_ups": [SubQuery(query=f.query, collection=f.collection) for f in follow_ups],
            "reviews": [*state.get("reviews", []), entry],
        }


def _admissible(follow_ups: list[FollowUp], user, searched: list[str]) -> list[FollowUp]:
    """Within the user's scope, and not a search already run."""
    seen = {q.lower() for q in searched}
    kept = []
    for f in follow_ups:
        if not user.allows(f.collection) or (f.collection == MATTER and not user.matter_id):
            continue
        if f.query.lower() in seen:
            continue
        seen.add(f.query.lower())
        kept.append(f)
    return kept
