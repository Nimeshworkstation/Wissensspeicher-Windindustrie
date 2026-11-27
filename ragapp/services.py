"""Reusable application services for other Django apps."""

from django.conf import settings
from functools import lru_cache


@lru_cache(maxsize=1)
def _embedding_manager():
    # Loading the local model is expensive; keep one instance for this process.
    from .src.embeddings import EmbeddingManager

    return EmbeddingManager()

def answer_question(question: str, *, top_k: int | None = None) -> dict:
    """Answer from indexed reports and return the source citations used."""
    question = question.strip()
    if not question:
        raise ValueError("Question cannot be empty.")
    if top_k is not None and top_k < 1:
        raise ValueError("top_k must be at least 1.")
    if not settings.GROQ_API_KEY:
        raise ValueError("Set API_KEY in the .env file before asking a question.")

    from .src.vectorstore_chromadb import ChromaVectorStore

    vector_store = ChromaVectorStore(
        persist_directory=str(settings.CHROMA_PATH)
    )
    if vector_store.collection.count() == 0:
        return {"answer": "I don't have enough context.", "sources": []}

    from .src.response_models.groq_response import GenerateGroqResponse
    from .src.response_models.prompt_utils import create_context, create_prompt

    query_embedding = _embedding_manager().generate_embedding([question])[0]
    retrieved_documents = vector_store.retrieve_documents(
        query_embedding,
        top_k=settings.RAG_TOP_K if top_k is None else top_k,
    )
    if not retrieved_documents:
        return {"answer": "I don't have enough context.", "sources": []}

    citation_context = create_context(retrieved_documents)
    prompt = create_prompt(question=question, context=citation_context["context"])

    llm = GenerateGroqResponse(
        api_key=settings.GROQ_API_KEY,
        model=settings.GROQ_MODEL,
    )
    answer = llm.generate_answer(prompt=prompt)
    return {"answer": answer, "sources": citation_context["sources"]}
