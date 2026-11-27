"""Tests for EmbeddingManager with SentenceTransformer patched (no model is loaded)."""

from unittest import mock

import numpy as np
from django.test import SimpleTestCase
from langchain_core.documents import Document

from ragapp.src import embeddings
from ragapp.src.embeddings import EmbeddingManager


class FakeModel:
    """Returns one 3-dimensional vector per input text."""

    def encode(self, texts, show_progress_bar=False):
        return np.ones((len(texts), 3))


class EmbeddingManagerTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch.object(embeddings, "SentenceTransformer", return_value=FakeModel())
        self.sentence_transformer = patcher.start()
        self.addCleanup(patcher.stop)

    def test_init_loads_model_by_name(self):
        manager = EmbeddingManager(model_name="my-model")
        self.sentence_transformer.assert_called_once_with("my-model")
        self.assertIsInstance(manager.model, FakeModel)

    def test_model_load_error_is_raised(self):
        self.sentence_transformer.side_effect = OSError("no model")
        with self.assertRaises(OSError):
            EmbeddingManager()

    def test_generate_embedding_without_model_raises(self):
        manager = EmbeddingManager()
        manager.model = None
        with self.assertRaises(ValueError):
            manager.generate_embedding(["x"])

    def test_generate_embedding_shape(self):
        manager = EmbeddingManager()
        self.assertEqual(manager.generate_embedding(["a", "b"]).shape, (2, 3))

    def test_short_document_is_one_chunk_with_metadata(self):
        manager = EmbeddingManager(chunk_size=100, chunk_overlap=0)
        chunks = manager.chunk_documents(
            [Document(page_content="short text", metadata={"source": "s"})]
        )
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["source"], "s")

    def test_long_document_is_split_into_chunks(self):
        manager = EmbeddingManager(chunk_size=20, chunk_overlap=0)
        text = " ".join(["word"] * 30)
        chunks = manager.chunk_documents([Document(page_content=text, metadata={"page": 1})])
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c.page_content) <= 20 for c in chunks))
        self.assertTrue(all(c.metadata["page"] == 1 for c in chunks))

    def test_embed_documents_returns_chunks_and_matching_embeddings(self):
        manager = EmbeddingManager(chunk_size=20, chunk_overlap=0)
        chunks, vectors = manager.embed_documents(
            [Document(page_content=" ".join(["word"] * 30))]
        )
        self.assertEqual(vectors.shape, (len(chunks), 3))

    def test_embed_documents_empty_returns_none(self):
        self.assertIsNone(EmbeddingManager().embed_documents([]))

    def test_embed_documents_without_text_returns_none(self):
        self.assertIsNone(EmbeddingManager().embed_documents([Document(page_content="")]))

    def test_embed_documents_count_mismatch_returns_none(self):
        manager = EmbeddingManager()
        manager.model = mock.Mock()
        manager.model.encode.return_value = np.ones((5, 3))
        self.assertIsNone(manager.embed_documents([Document(page_content="one chunk")]))
