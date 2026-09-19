"""Decide where and what to search before searching.

The reference architecture's Query Agent inspects the collections, breaks a
question into sub-queries, routes each to a collection and attaches structured
filters. This is that step, as one structured LLM call: the model sees the
catalog and returns a `QueryPlan`, validated by Pydantic before anything
downstream trusts it.

What the planner may decide is deliberately narrow. It chooses collections,
splits the question, and may add a court or year restriction *when the question
names one*. It cannot widen the user's own filters, cannot invent a court code
the catalog doesn't list, and cannot answer - retrieval and generation are
separate nodes that take its plan as input, not its opinion.
"""

import logging
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel

from app.caching import TTLCache
from app.matters.catalog import describe_matter
from app.matters.store import MatterStore
from app.retrieval.catalog import Catalog
from app.retrieval.filters import collections_in_scope
from app.retrieval.plan import QueryPlan, constrain, fallback_plan
from app.retrieval.prompts import PLANNER_PROMPT
from app.retrieval.state import GraphState
from app.tracing import linked_prompt, observation

logger = logging.getLogger(__name__)


def plan(
    state: GraphState,
    llm: BaseChatModel,
    catalog: Callable[[], Catalog],
    max_subqueries: int,
    enabled: bool = True,
    cache: TTLCache | None = None,
    matters: MatterStore | None = None,
) -> dict:
    """Decide where to search. `catalog` is a callable so a refreshed catalog is seen.

    Plans are cached by question and user filters: the same question asked twice
    should not pay for planning twice, and a plan is a deterministic function of
    exactly those two inputs plus the catalog, which changes on the order of
    minutes. A matter's documents change with every upload, so its version is
    part of the key too.
    """
    user = state["user_filters"]
    scope = collections_in_scope(user)
    if not enabled:
        return {"plan": fallback_plan(state["question"], scope)}

    matter = matters.get(user.matter_id) if matters and user.matter_id else None
    key = TTLCache.key(
        "plan", state["question"], repr(user.describe()), matter.updated_at if matter else ""
    )
    if cache is not None and (hit := cache.get(key)) is not None:
        return {"plan": hit}

    catalog_text = catalog().for_planner()
    if matter is not None:
        catalog_text = f"{catalog_text}\n{describe_matter(matter)}"

    with observation(
        as_type="chain",
        name="plan-query",
        input={"question": state["question"], "user_filters": user.describe()},
        metadata={"prompt": PLANNER_PROMPT.name, "prompt_version": PLANNER_PROMPT.version},
    ) as span:
        try:
            planner = llm.with_structured_output(QueryPlan)
            message = PLANNER_PROMPT.template.invoke(
                {
                    "catalog": catalog_text,
                    "collections": ", ".join(scope),
                    "max_subqueries": max_subqueries,
                    "question": state["question"],
                }
            )
            with linked_prompt(PLANNER_PROMPT.name):
                result = planner.invoke(
                    message,
                    config={
                        "metadata": {
                            "prompt": PLANNER_PROMPT.name,
                            "prompt_version": PLANNER_PROMPT.version,
                        }
                    },
                )
            produced = constrain(result, user, catalog(), max_subqueries)
        except Exception as exc:  # noqa: BLE001 - any planner failure degrades the same way
            logger.warning("planner failed (%s); using fallback plan", exc)
            produced = fallback_plan(state["question"], scope)

        span.update(
            output=produced.model_dump(),
            metadata={"origin": produced.origin, "sub_queries": len(produced.sub_queries)},
        )
        # A fallback is not worth remembering: the next request should try the
        # planner again rather than inherit an outage.
        if cache is not None and produced.origin == "planner":
            cache.set(key, produced)
        return {"plan": produced}
