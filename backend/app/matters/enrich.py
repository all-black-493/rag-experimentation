"""One model call per indexed document: what it is, who is in it, when.

Runs after indexing, never instead of it. A document is searchable the moment
its chunks are in; the profile is what the planner reads to route "what does
my contract say" to the contract, and what the reader sees in the rail. If
the call fails the document keeps its place and records why the profile is
missing - a provider outage must not make an upload look lost.
"""

import logging

from langchain_core.language_models import BaseChatModel

from app.matters.models import DocumentProfile
from app.prompts import load_chat_prompt
from app.tracing import linked_prompt, observation

logger = logging.getLogger(__name__)

PROFILE_PROMPT = load_chat_prompt("profile")

# Roughly the opening pages. Enough to identify a document; a 300-page bundle
# doesn't need to be read whole to be described.
_MAX_CHARS = 12_000


def profile_document(llm: BaseChatModel, name: str, text: str) -> DocumentProfile:
    with observation(
        as_type="chain",
        name="profile-document",
        input={"name": name, "chars": len(text)},
        metadata={"prompt": PROFILE_PROMPT.name, "prompt_version": PROFILE_PROMPT.version},
    ) as span:
        message = PROFILE_PROMPT.template.invoke({"name": name, "text": text[:_MAX_CHARS]})
        with linked_prompt(PROFILE_PROMPT.name):
            profile = llm.with_structured_output(DocumentProfile).invoke(
                message,
                config={
                    "metadata": {
                        "prompt": PROFILE_PROMPT.name,
                        "prompt_version": PROFILE_PROMPT.version,
                    }
                },
            )
        span.update(output=profile.model_dump())
        return profile
