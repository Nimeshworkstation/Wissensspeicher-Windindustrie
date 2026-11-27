"""Tests for the import_context_documents management command (step 1 of the RAG pipeline).

Runs against a temporary folder with BASE_DIR / RAG_LOG_DIR overridden, so the real
data/ and logs/ folders are never touched.
"""

import hashlib
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from ragapp.models import IndexedFile


class ImportContextDocumentsTests(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.folder = self.base / "context"
        self.folder.mkdir()
        override = override_settings(BASE_DIR=self.base, RAG_LOG_DIR=self.base / "logs")
        override.enable()
        self.addCleanup(override.disable)

    def _run(self, folder=None):
        out = StringIO()
        call_command("import_context_documents", folder=folder or self.folder, stdout=out)
        return out.getvalue()

    def test_new_pdf_and_txt_are_created_pending(self):
        (self.folder / "a.txt").write_bytes(b"text file")
        (self.folder / "b.pdf").write_bytes(b"%PDF-1.4 fake")

        output = self._run()

        records = {r.path: r for r in IndexedFile.objects.all()}
        self.assertEqual(set(records), {"context/a.txt", "context/b.pdf"})
        self.assertTrue(all(r.status == "pending" for r in records.values()))
        self.assertEqual(bytes(records["context/a.txt"].original_file), b"text file")
        self.assertEqual(
            records["context/a.txt"].content_hash, hashlib.sha256(b"text file").hexdigest()
        )
        self.assertIn("2 new, 0 changed, 0 unchanged, 0 skipped.", output)

    def test_second_run_leaves_files_unchanged(self):
        (self.folder / "a.txt").write_bytes(b"text file")
        self._run()
        IndexedFile.objects.update(status="indexed")

        output = self._run()

        self.assertIn("0 new, 0 changed, 1 unchanged, 0 skipped.", output)
        self.assertEqual(IndexedFile.objects.get().status, "indexed")

    def test_changed_content_sets_status_back_to_pending(self):
        path = self.folder / "a.txt"
        path.write_bytes(b"version 1")
        self._run()
        IndexedFile.objects.update(status="failed", error="old problem")
        path.write_bytes(b"version 2")

        output = self._run()

        record = IndexedFile.objects.get()
        self.assertEqual(record.status, "pending")
        self.assertEqual(record.error, "")
        self.assertEqual(record.content_hash, hashlib.sha256(b"version 2").hexdigest())
        self.assertEqual(bytes(record.original_file), b"version 2")
        self.assertIn("0 new, 1 changed, 0 unchanged, 0 skipped.", output)

    def test_unsupported_file_is_skipped(self):
        (self.folder / "report.docx").write_bytes(b"word")
        output = self._run()
        self.assertFalse(IndexedFile.objects.exists())
        self.assertIn("0 new, 0 changed, 0 unchanged, 1 skipped.", output)

    def test_subfolders_are_ignored(self):
        (self.folder / "sub").mkdir()
        (self.folder / "sub" / "inner.txt").write_bytes(b"x")
        self._run()
        self.assertFalse(IndexedFile.objects.exists())

    def test_uppercase_extension_is_supported(self):
        (self.folder / "UPPER.PDF").write_bytes(b"%PDF")
        self._run()
        self.assertTrue(IndexedFile.objects.filter(path="context/UPPER.PDF").exists())

    def test_missing_folder_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._run(folder=self.base / "does-not-exist")

    def test_disappeared_file_is_reported_but_kept(self):
        path = self.folder / "gone.txt"
        path.write_bytes(b"x")
        self._run()
        path.unlink()

        output = self._run()

        self.assertIn("missing   context/gone.txt (kept in database)", output)
        self.assertTrue(IndexedFile.objects.filter(path="context/gone.txt").exists())

    def test_records_from_other_folders_are_not_reported_missing(self):
        IndexedFile.objects.create(path="other/x.txt", content_hash="h", original_file=b"")
        output = self._run()
        self.assertNotIn("other/x.txt", output)

    def test_folder_outside_base_dir_stores_absolute_path(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as outside:
            outside = Path(outside).resolve()
            (outside / "a.txt").write_bytes(b"x")
            self._run(folder=outside)
        self.assertEqual(IndexedFile.objects.get().path, (outside / "a.txt").as_posix())

    def test_run_is_logged_with_start_and_success(self):
        (self.folder / "a.txt").write_bytes(b"x")
        with self.assertLogs("ragapp.management.commands.import_context_documents", "INFO") as logs:
            self._run()
        messages = "\n".join(logs.output)
        self.assertIn("STARTED: import_context_documents", messages)
        self.assertIn("NEW: context/a.txt", messages)
        self.assertIn("SUCCEEDED: import_context_documents", messages)

    def test_failed_run_is_logged(self):
        with self.assertLogs("ragapp.management.commands.import_context_documents", "ERROR") as logs:
            with self.assertRaises(CommandError):
                self._run(folder=self.base / "does-not-exist")
        self.assertIn("FAILED: import_context_documents", "\n".join(logs.output))
