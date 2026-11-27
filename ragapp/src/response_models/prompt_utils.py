def create_prompt(question: str, context: str):
    if not context:
        return None
    if not question.strip():
        return None

    return f"""
        You answer questions about the German wind industry using only the supplied report excerpts.
        Do not use outside knowledge or invent facts, page numbers, report titles, or citations.
        If the excerpts do not support an answer, say exactly: "I don't have enough context."
        Answer in the same language as the question. Keep the answer concise and factual.
        Cite every factual claim with the bracketed source
        label shown before the excerpt, for example [1]. Use only labels present in the context.

        Context:
        {context}

        Question:
        {question}

        Answer:
        """


def create_context(retrieved_docs):
    """Build labeled report excerpts and their user-facing citation details."""
    excerpts = []
    sources = []

    for citation_id, doc in enumerate(retrieved_docs, start=1):
        metadata = doc.get("metadata") or {}
        source = metadata.get("file_name") or metadata.get("source") or "Unknown source"
        page = metadata.get("page")
        # PyPDFLoader records zero-based page indices; citations use printed-style numbering.
        page_number = int(page) + 1 if page is not None else None
        reference = f"{source}, p. {page_number}" if page_number is not None else source
        excerpts.append(f"[{citation_id}] {reference}\n{doc.get('content', '')}")
        sources.append(
            {
                "citation": citation_id,
                "title": source,
                "source": metadata.get("source", source),
                "page": page_number,
                "similarity_score": doc.get("similarity_score"),
            }
        )

    return {"context": "\n\n".join(excerpts), "sources": sources}
