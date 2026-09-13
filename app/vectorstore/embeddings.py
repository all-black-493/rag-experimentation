from langchain_cohere import CohereEmbeddings

from app.config import Settings


def build_embeddings(settings: Settings) -> CohereEmbeddings:
    return CohereEmbeddings(model=settings.embedding_model, cohere_api_key=settings.cohere_api_key)
