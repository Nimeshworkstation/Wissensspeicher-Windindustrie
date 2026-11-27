"""Tests for the import_rag_documents management command (step 2 of the RAG pipeline).

EmbeddingManager, ChromaVectorStore and _index_record are patched, so no model is
loaded and no vector store is written. CHROMA_PATH / RAG_LOG_DIR point to a temp dir.
"""

import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from ragapp.models import IndexedFile


class ImportRagDocumentsTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        override = override_settings(
            CHROMA_PATH=self.base / "chroma", RAG_LOG_DIR=self.base / "logs"
        )
        override.enable()
        self.addCleanup(override.disable)

        patches = {
            "embedding_cls": "ragapp.src.embeddings.EmbeddingManager",
            "store_cls": "ragapp.src.vectorstore_chromadb.ChromaVectorStore",
            "index_record": "ragapp.tasks._index_record",
        }
        for attribute, target in patches.items():
            patcher = mock.patch(target)
            setattr(self, attribute, patcher.start())
            self.addCleanup(patcher.stop)
        self.index_record.return_value = 3

    def _run(self):
        out = StringIO()
        call_command("import_rag_documents", stdout=out)
        return out.getvalue()

    def _record(self, path, status="pending"):
        return IndexedFile.objects.create(
            path=path, content_hash="h", original_file=b"x", status=status
        )

    def test_no_pending_documents_reports_success(self):
        self._record("done.txt", status="indexed")
        output = self._run()
        self.assertIn("No pending documents found in the database.", output)
        self.embedding_cls.assert_not_called()
        self.store_cls.assert_not_called()
        self.index_record.assert_not_called()

    def test_pending_processing_and_failed_records_are_indexed(self):
        for path, status in [("a.txt", "pending"), ("b.txt", "processing"),
                             ("c.txt", "failed"), ("d.txt", "indexed")]:
            self._record(path, status=status)

        output = self._run()

        indexed_paths = [c.args[0].path for c in self.index_record.call_args_list]
        self.assertEqual(indexed_paths, ["a.txt", "b.txt", "c.txt"])
        self.assertIn("Indexed 3 database document(s), 0 failed, 9 chunk(s).", output)

    def test_model_and_store_created_once_and_shared(self):
        self._record("a.txt")
        self._record("b.txt")
        self._run()

        self.embedding_cls.assert_called_once_with()
        self.store_cls.assert_called_once_with(persist_directory=str(self.base / "chroma"))
        for call in self.index_record.call_args_list:
            self.assertIs(call.args[1], self.embedding_cls.return_value)
            self.assertIs(call.args[2], self.store_cls.return_value)

    def test_failing_record_is_marked_failed_and_command_errors(self):
        good = self._record("good.txt")
        bad = self._record("bad.txt")

        def fake_index(record, embedding_manager, store):
            if record.path == "bad.txt":
                raise ValueError("cannot parse")
            return 1

        self.index_record.side_effect = fake_index
        with self.assertRaises(CommandError) as raised:
            self._run()

        self.assertIn("1 failed", str(raised.exception))
        bad.refresh_from_db()
        good.refresh_from_db()
        self.assertEqual(bad.status, "failed")
        self.assertEqual(bad.error, "cannot parse")
        self.assertEqual(good.status, "pending")  # untouched by the mocked indexer

    def test_unexpected_setup_error_becomes_command_error(self):
        self._record("a.txt")
        self.embedding_cls.side_effect = OSError("model missing")
        with self.assertRaises(CommandError) as raised:
            self._run()
        self.assertIn("RAG import failed: model missing", str(raised.exception))

    def test_run_is_logged_with_start_and_success(self):
        with self.assertLogs("ragapp.management.commands.import_rag_documents", "INFO") as logs:
            self._run()
        messages = "\n".join(logs.output)
        self.assertIn("STARTED: import_rag_documents", messages)
        self.assertIn("SUCCEEDED: import_rag_documents", messages)
