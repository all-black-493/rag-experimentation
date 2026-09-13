from asyncer import asyncify
from fastapi import APIRouter, Request
from langgraph.graph.state import CompiledStateGraph

from app.api.schemas import Citation, QueryRequest, QueryResponse
from app.config import get_settings
from app.dependencies import GraphDep, TenantDep
from app.rate_limit import limiter
from app.retrieval.citations import build_citations
from app.scoring import citation_coverage
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

        try:
            result = graph.invoke({"question": question, "tenant": tenant}, config=config)
        except Exception:
            # An errored request would otherwise leave a trace with no scores at
            # all, which reads the same as a trace that was never sent.
            root.score_trace(name="failed", value=True, data_type="BOOLEAN")
            raise
        root.score_trace(name="failed", value=False, data_type="BOOLEAN")

        citation_count = len(result["documents"])
        answered = bool(result["documents"])
        report = citation_coverage(result["answer"], citation_count)

        root.update(
            output={"answer": result["answer"], "citations": citation_count},
            metadata={
                "grounded": result.get("grounded"),
                "declined": not answered,
                "cited_indices": report.cited_indices,
                "unused_citations": report.unused_citations,
                "invalid_indices": report.invalid_indices,
            },
        )

        # Scores rather than metadata, because these are the series we track over
        # time - Langfuse aggregates scores, it doesn't aggregate metadata.
        root.score_trace(name="answered", value=answered, data_type="BOOLEAN")
        if answered:
            root.score_trace(
                name="citation_coverage", value=report.coverage, data_type="NUMERIC"
            )
            root.score_trace(
                name="grounded", value=bool(result.get("grounded")), data_type="BOOLEAN"
            )
            # A marker pointing at a citation that doesn't exist is the model
            # inventing a reference, which coverage alone would score as a hit.
            root.score_trace(
                name="invalid_citations", value=float(len(report.invalid_indices)),
                data_type="NUMERIC",
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
