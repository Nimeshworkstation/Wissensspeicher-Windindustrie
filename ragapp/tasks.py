"""Index document bytes already stored in Django into the Chroma vector store.

Started with `python manage.py import_rag_documents`.
"""
import logging
import tempfile
from pathlib import Path

from django.conf import settings

from .src.data_loader import load_file
from .src.embeddings import EmbeddingManager
from .src.vectorstore_chromadb import ChromaVectorStore

from .models import IndexedFile

logger = logging.getLogger(__name__)
activity_logger = logging.getLogger("ragapp.activity")
# Everything except "indexed" is (re)tried; "processing" can be left over
# from an interrupted run.
TO_INDEX = ("pending", "processing", "failed")


def _index_record(record, embedding_manager, store):
    """Load one record's bytes from the database, embed them, and write them to Chroma."""
    record.status = "processing"
    record.error = ""
    record.save(update_fields=["status", "error", "updated_at"])

    original_path = Path(record.path)
    if original_path.suffix.lower() == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader

        loader_type, encoding = PyPDFLoader, None
    elif original_path.suffix.lower() == ".txt":
        from langchain_community.document_loaders import TextLoader

        loader_type, encoding = TextLoader, "utf-8"
    else:
        raise ValueError("Only PDF and TXT files are supported.")

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_path = Path(temporary_directory) / original_path.name
        temporary_path.write_bytes(bytes(record.original_file))
        documents = load_file(loader_type, [temporary_path], encoding=encoding)
    for document in documents:
        document.metadata["source"] = record.path
        document.metadata["file_name"] = original_path.name
    embedded = embedding_manager.embed_documents(documents)
    if not embedded:
        raise ValueError("No text chunks could be generated.")

    store.collection.delete(where={"source": record.path})
    store.add_documents(*embedded)
    record.status = "indexed"
    record.save(update_fields=["status", "updated_at"])
    return len(embedded[0])


def index_documents():
    """Index every non-indexed document already stored in the Django database."""
    records = list(IndexedFile.objects.filter(status__in=TO_INDEX).order_by("pk"))
    indexed = failed = 0
    if records:
        # Load the embedding model and the store once for the whole run.
        embedding_manager = EmbeddingManager()
        store = ChromaVectorStore(persist_directory=str(settings.CHROMA_PATH))
        for record in records:
            name = Path(record.path).name
            try:
                chunks = _index_record(record, embedding_manager, store)
                indexed += 1
                activity_logger.info("Indexed %s: %d text chunk(s)", name, chunks)
            except Exception as exc:
                failed += 1
                logger.exception("Indexing failed for %s", record.path)
                record.status = "failed"
                record.error = str(exc)
                record.save(update_fields=["status", "error", "updated_at"])
                activity_logger.error("Indexing failed for %s: %s", name, exc)

    result = {"indexed": indexed, "failed": failed}
    activity_logger.info("Document indexing run finished: %s", result)
    return result
