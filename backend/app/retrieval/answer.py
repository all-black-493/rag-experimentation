"""Ask mode's tail: generate a cited answer, then check it against its sources."""

from langchain_core.language_models import BaseChatModel

from app.retrieval.citations import format_context
from app.retrieval.grounding import DECLINE_MESSAGE, VERIFY_PROMPT, GroundednessCheck
from app.retrieval.prompts import GENERATION_PROMPT
from app.retrieval.state import GraphState
from app.tracing import linked_prompt, observation


def _prompt_metadata(prompt) -> dict:
    """Tag the LLM call with the prompt revision that produced it.

    Rides along on the invoke config so it lands on the generation itself - the
    callback handler captures the rendered messages but has no idea which
    versioned template in prompts/ they came from.
    """
    return {"metadata": {"prompt": prompt.name, "prompt_version": prompt.version}}


def generate(state: GraphState, llm: BaseChatModel) -> dict:
    # No wrapping span here: LangGraph's callback already emits one named after
    # this node, and a second identically-named span just doubles the tree.
    context = format_context(state["documents"])
    message = GENERATION_PROMPT.template.invoke(
        {"context": context, "question": state["question"]}
    )
    with linked_prompt(GENERATION_PROMPT.name):
        response = llm.invoke(message, config=_prompt_metadata(GENERATION_PROMPT))
    # .text (not .content) because content can be a list of blocks - e.g. Claude's
    # adaptive thinking, on by default, adds a thinking block alongside the text one.
    return {"answer": response.text}


def verify(state: GraphState, llm: BaseChatModel) -> dict:
    """Judge the answer against its passages. Withdrawn only on two independent verdicts.

    The judge is a sampled model call and disagrees with itself a few percent of
    the time. A single "not grounded" therefore gets a second opinion; the answer
    is withdrawn only when both say so. The cost - one extra call - is paid only
    on failures, and a good answer is no longer lost to one unlucky sample.

    `llm` must be an uncached model: caching a judgment would freeze one verdict
    on one answer for the life of the process.
    """
    # "evaluator" rather than a plain span: this call judges another call's output,
    # which is what that observation type is for.
    with observation(
        as_type="evaluator",
        name="verify-groundedness",
        input={"question": state["question"], "answer": state["answer"]},
        metadata={"prompt": VERIFY_PROMPT.name, "prompt_version": VERIFY_PROMPT.version},
    ) as span:
        checker = llm.with_structured_output(GroundednessCheck)
        context = format_context(state["documents"])
        message = VERIFY_PROMPT.template.invoke(
            {"context": context, "question": state["question"], "answer": state["answer"]}
        )
        verdicts: list[GroundednessCheck] = []
        with linked_prompt(VERIFY_PROMPT.name):
            for _ in range(2):
                verdicts.append(checker.invoke(message, config=_prompt_metadata(VERIFY_PROMPT)))
                if verdicts[-1].grounded:
                    break
        grounded = any(v.grounded for v in verdicts)
        span.update(
            output={"grounded": grounded, "reasons": [v.reason for v in verdicts]},
            metadata={"verdicts": len(verdicts)},
        )
        return {"grounded": grounded}


def decline(state: GraphState) -> dict:
    # `grounded` is left as the verifier set it (or None if it never ran), so
    # callers can tell a withdrawn answer from one that was never generated.
    return {"answer": DECLINE_MESSAGE, "documents": []}
