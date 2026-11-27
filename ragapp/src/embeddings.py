from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

import logging

logger = logging.getLogger(__name__)   # -> logs/rag/ragapp.log (settings.LOGGING)


class EmbeddingManager:
    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        chunk_size=2000,
        chunk_overlap=200,
        upload_types=[],
    ):
        logger.info("Embedding pipeline started")
        self.model_name = model_name
        self.model = None
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._load_model()
        self.upload_types = upload_types

    def _load_model(self):
        try:
            logger.info("Loading embedding model %s", self.model_name)
            self.model = SentenceTransformer(self.model_name)
            logger.info("Embedding model %s loaded", self.model_name)
        except Exception as e:
            logger.error("Error loading model %s: %s", self.model_name, e)
            raise

    def chunk_documents(self, document: List[Document]):
        total_chunks = []
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
        )

        chunks = text_splitter.split_documents(documents=document)
        total_chunks.extend(chunks)
        logger.info("Chunked %d source document page(s) into %d chunk(s)", len(document), len(total_chunks))
        return total_chunks

    def generate_embedding(self, texts: List[str]) -> np.ndarray:
        if not self.model:
            raise ValueError("Model not found")
        logger.info("Generating embeddings for %d text(s)", len(texts))
        embeddings = self.model.encode(texts, show_progress_bar=True)
        logger.info("Generated embeddings with shape %s", embeddings.shape)
        return embeddings

    def embed_documents(self, documents):
        logger.info("Step 1/3: loading documents")

        if not documents:
            logger.warning("No documents loaded")
            return None

        logger.info("Step 2/3: chunking documents")
        chunks = self.chunk_documents(documents)

        if not chunks:
            logger.warning("No chunks created")
            return None

        logger.info("Step 3/3: generating embeddings")
        chunk_text = [chunk.page_content for chunk in chunks]
        embeddings = self.generate_embedding(chunk_text)
        if len(chunks) != len(embeddings):
            logger.error("Chunk count (%d) does not match embedding count (%d)", len(chunks), len(embeddings))
            return None
        return chunks, embeddings


def main():
    em = EmbeddingManager()
    em.embed_documents(path="../data", file_types=["txt", "pdf"])


if __name__ == "__main__":
    main()
