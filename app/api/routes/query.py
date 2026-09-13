from asyncer import asyncify
from fastapi import APIRouter, Request
from langgraph.graph.state import CompiledStateGraph

from app.api.schemas import Citation, QueryRequest, QueryResponse
from app.config import get_settings
from app.dependencies import GraphDep, TenantDep
from app.rate_limit import limiter
from app.retrieval.citations import build_citations
from app.tracing import build_callback_handler, trace

router = APIRouter(prefix="/query", tags=["query"])
_rate_limit = get_settings().rate_limit_query


def _run_graph(graph: CompiledStateGraph, question: str, tenant: str) -> dict:
    """Run one query under a single root trace.

    Synchronous and self-contained on purpose: the route hands the whole thing to
    a worker thread, and the active-observation context is thread-local, so the
    root span has to be opened on the same thread the graph nodes run on.
    """
    with trace(name="rag-query", session_id=tenant, input={"question": question}) as root:
        handler = build_callback_handler()
        config = {"callbacks": [handler]} if handler else {}
        result = graph.invoke({"question": question, "tenant": tenant}, config=config)

        root.update(
            output={"answer": result["answer"], "citations": len(result["documents"])},
            metadata={"grounded": result.get("grounded"), "declined": not result["documents"]},
        )
        return result


@router.post("")
@limiter.limit(_rate_limit)
async def answer_question(
    request: Request, payload: QueryRequest, graph: GraphDep, tenant: TenantDep
) -> QueryResponse:
    result = await asyncify(_run_graph)(graph, payload.question, tenant)
    citations = [Citation(**citation) for citation in build_citations(result["documents"])]
    return QueryResponse(answer=result["answer"], citations=citations)
