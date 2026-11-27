"""Tests for ChromaVectorStore with a temporary persist directory and tiny 3-dim vectors.

No embedding model is used; embeddings are hand-made numpy arrays.
"""

import os
import tempfile

import numpy as np
from django.test import SimpleTestCase
from langchain_core.documents import Document

# Keep Chroma from sending anonymous telemetry during tests (no network).
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from ragapp.src.vectorstore_chromadb import ChromaVectorStore  # noqa: E402


def _close_store(store):
    """Release Chroma's file handles so Windows can delete the temp directory."""
    try:
        store.client._system.stop()
    except Exception:
        pass
    try:
        from chromadb.api.client import SharedSystemClient

        SharedSystemClient.clear_system_cache()
    except Exception:
        pass


class ChromaVectorStoreTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.persist_directory = os.path.join(tmp.name, "chroma")
        self.store = ChromaVectorStore(
            collection_name="test-docs", persist_directory=self.persist_directory
        )
        self.addCleanup(_close_store, self.store)

    def _add_two_documents(self):
        documents = [
            Document(page_content="about wind", metadata={"source": "a.txt", "file_name": "a.txt"}),
            Document(page_content="about solar", metadata={"source": "b.pdf", "page": 0}),
        ]
        embeddings = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        self.store.add_documents(documents, embeddings)

    def test_store_creates_persist_directory_and_empty_collection(self):
        self.assertTrue(os.path.isdir(self.persist_directory))
        self.assertEqual(self.store.collection.count(), 0)

    def test_collection_uses_cosine_distance(self):
        self.assertEqual(self.store.collection.metadata["hnsw:space"], "cosine")

    def test_add_documents_length_mismatch_raises(self):
        with self.assertRaises(RuntimeError):
            self.store.add_documents([Document(page_content="x")], np.ones((2, 3)))

    def test_add_documents_stores_chunks_with_extra_metadata(self):
        self._add_two_documents()
        self.assertEqual(self.store.collection.count(), 2)
        stored = self.store.collection.get(where={"source": "a.txt"})
        self.assertEqual(stored["documents"], ["about wind"])
        self.assertEqual(stored["metadatas"][0]["doc_index"], 0)
        self.assertEqual(stored["metadatas"][0]["content_length"], len("about wind"))

    def test_adding_same_documents_twice_upserts(self):
        self._add_two_documents()
        self._add_two_documents()
        self.assertEqual(self.store.collection.count(), 2)

    def test_retrieve_returns_closest_document_first(self):
        self._add_two_documents()
        results = self.store.retrieve_documents(np.array([1.0, 0.0, 0.0]), top_k=2)
        self.assertEqual([r["content"] for r in results], ["about wind", "about solar"])
        self.assertEqual([r["rank"] for r in results], [1, 2])
        self.assertAlmostEqual(results[0]["similarity_score"], 1.0, places=4)
        self.assertAlmostEqual(results[0]["distance"], 0.0, places=4)
        self.assertEqual(results[1]["metadata"]["page"], 0)

    def test_retrieve_respects_top_k(self):
        self._add_two_documents()
        results = self.store.retrieve_documents(np.array([1.0, 0.0, 0.0]), top_k=1)
        self.assertEqual(len(results), 1)

    def test_score_threshold_filters_dissimilar_documents(self):
        self._add_two_documents()
        results = self.store.retrieve_documents(
            np.array([1.0, 0.0, 0.0]), top_k=2, score_threshold=0.5
        )
        self.assertEqual([r["content"] for r in results], ["about wind"])

    def test_retrieve_from_empty_collection_returns_empty_list(self):
        self.assertEqual(self.store.retrieve_documents(np.array([1.0, 0.0, 0.0])), [])

    def test_delete_by_source_removes_only_that_source(self):
        self._add_two_documents()
        self.store.collection.delete(where={"source": "a.txt"})
        self.assertEqual(self.store.collection.count(), 1)

    def test_create_chunk_id_is_deterministic_and_depends_on_index(self):
        chunk = Document(page_content="text", metadata={"source": "s", "page": 1})
        self.assertEqual(self.store.create_chunk_id(chunk, 0), self.store.create_chunk_id(chunk, 0))
        self.assertNotEqual(self.store.create_chunk_id(chunk, 0), self.store.create_chunk_id(chunk, 1))
        self.assertEqual(len(self.store.create_chunk_id(chunk, 0)), 64)
