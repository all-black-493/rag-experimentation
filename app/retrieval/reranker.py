from langchain_cohere import CohereRerank

from app.config import Settings


def build_reranker(settings: Settings) -> CohereRerank:
    return CohereRerank(
        model=settings.rerank_model,
        cohere_api_key=settings.cohere_api_key,
        top_n=settings.rerank_top_n,
    )
