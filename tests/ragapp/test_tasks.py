"""Tests for ragapp.tasks (_index_record and index_documents) with a mocked
embedding manager and vector store, so no model or Chroma store is used."""

import tempfile
from unittest import mock

import numpy as np
from django.test import TestCase, override_settings
from langchain_core.documents import Document

from ragapp import tasks
from ragapp.models import IndexedFile


def _embed_like_real(documents):
    """Stand-in for EmbeddingManager.embed_documents: one chunk per document."""
    return list(documents), np.ones((len(documents), 3))


class IndexRecordTests(TestCase):
    def setUp(self):
        self.embedding_manager = mock.Mock()
        self.embedding_manager.embed_documents.side_effect = _embed_like_real
        self.store = mock.Mock()

    def _record(self, path, content=b"Wind power text", status="pending"):
        return IndexedFile.objects.create(
            path=path, content_hash="h", original_file=content, status=status, error="old error"
        )

    def test_txt_record_is_indexed(self):
        record = self._record("data/context/notes.txt")
        chunks = tasks._index_record(record, self.embedding_manager, self.store)

        self.assertEqual(chunks, 1)
        record.refresh_from_db()
        self.assertEqual(record.status, "indexed")
        self.assertEqual(record.error, "")

    def test_old_chunks_are_deleted_by_source_before_adding(self):
        record = self._record("data/context/notes.txt")
        tasks._index_record(record, self.embedding_manager, self.store)

        self.store.collection.delete.assert_called_once_with(
            where={"source": "data/context/notes.txt"}
        )
        self.store.add_documents.assert_called_once()
        self.assertEqual(
            [c[0] for c in self.store.method_calls if c[0] in ("collection.delete", "add_documents")],
            ["collection.delete", "add_documents"],
        )

    def test_loaded_documents_carry_record_path_and_file_name(self):
        record = self._record("data/context/notes.txt", content="Grüße".encode("utf-8"))
        tasks._index_record(record, self.embedding_manager, self.store)

        documents = self.embedding_manager.embed_documents.call_args.args[0]
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].page_content, "Grüße")
        self.assertEqual(documents[0].metadata["source"], "data/context/notes.txt")
        self.assertEqual(documents[0].metadata["file_name"], "notes.txt")

    def test_add_documents_receives_chunks_and_embeddings(self):
        record = self._record("data/context/notes.txt")
        tasks._index_record(record, self.embedding_manager, self.store)

        chunks, vectors = self.store.add_documents.call_args.args
        self.assertIsInstance(chunks[0], Document)
        self.assertEqual(vectors.shape, (1, 3))

    def test_unsupported_extension_raises(self):
        record = self._record("data/context/report.docx")
        with self.assertRaises(ValueError):
            tasks._index_record(record, self.embedding_manager, self.store)
        self.store.add_documents.assert_not_called()

    def test_no_chunks_raises_and_store_is_untouched(self):
        self.embedding_manager.embed_documents.side_effect = None
        self.embedding_manager.embed_documents.return_value = None
        record = self._record("data/context/empty.txt", content=b"")
        with self.assertRaises(ValueError):
            tasks._index_record(record, self.embedding_manager, self.store)
        self.store.collection.delete.assert_not_called()
        self.store.add_documents.assert_not_called()


class IndexDocumentsTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        override = override_settings(CHROMA_PATH=tmp.name)
        override.enable()
        self.addCleanup(override.disable)

        for target in ("EmbeddingManager", "ChromaVectorStore"):
            patcher = mock.patch.object(tasks, target)
            setattr(self, target, patcher.start())
            self.addCleanup(patcher.stop)

    def test_nothing_to_index_does_not_load_model(self):
        IndexedFile.objects.create(path="a.txt", content_hash="h", original_file=b"", status="indexed")
        self.assertEqual(tasks.index_documents(), {"indexed": 0, "failed": 0})
        self.EmbeddingManager.assert_not_called()
        self.ChromaVectorStore.assert_not_called()

    def test_failed_record_is_marked_and_others_continue(self):
        good = IndexedFile.objects.create(path="good.txt", content_hash="h", original_file=b"")
        bad = IndexedFile.objects.create(path="bad.txt", content_hash="h", original_file=b"")

        def fake_index(record, embedding_manager, store):
            if record.path == "bad.txt":
                raise ValueError("broken file")
            record.status = "indexed"
            record.save()
            return 2

        with mock.patch.object(tasks, "_index_record", side_effect=fake_index):
            result = tasks.index_documents()

        self.assertEqual(result, {"indexed": 1, "failed": 1})
        good.refresh_from_db()
        bad.refresh_from_db()
        self.assertEqual(good.status, "indexed")
        self.assertEqual(bad.status, "failed")
        self.assertEqual(bad.error, "broken file")
