"""Tests for the IndexedFile model (defaults, string form, unique path)."""

from django.db import IntegrityError
from django.test import TestCase

from ragapp.models import IndexedFile


class IndexedFileModelTests(TestCase):
    def test_default_status_is_pending_and_error_empty(self):
        record = IndexedFile.objects.create(
            path="data/context/a.txt", content_hash="abc", original_file=b"x"
        )
        self.assertEqual(record.status, "pending")
        self.assertEqual(record.error, "")

    def test_str_contains_path_and_status(self):
        record = IndexedFile(path="data/context/a.txt", status="indexed")
        self.assertEqual(str(record), "data/context/a.txt (indexed)")

    def test_original_file_round_trips_bytes(self):
        record = IndexedFile.objects.create(
            path="data/context/b.txt", content_hash="h", original_file=b"hello \x00 bytes"
        )
        record.refresh_from_db()
        self.assertEqual(bytes(record.original_file), b"hello \x00 bytes")

    def test_path_is_unique(self):
        IndexedFile.objects.create(path="same.txt", content_hash="1", original_file=b"")
        with self.assertRaises(IntegrityError):
            IndexedFile.objects.create(path="same.txt", content_hash="2", original_file=b"")

    def test_updated_at_is_set_automatically(self):
        record = IndexedFile.objects.create(path="c.txt", content_hash="1", original_file=b"")
        self.assertIsNotNone(record.updated_at)
