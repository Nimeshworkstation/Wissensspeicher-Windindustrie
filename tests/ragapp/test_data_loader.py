"""Tests for ragapp.src.data_loader (load_file / load_all_documents) with temporary TXT files."""

import tempfile
from pathlib import Path

from django.test import SimpleTestCase
from langchain_community.document_loaders import TextLoader

from ragapp.src.data_loader import load_all_documents, load_file


class LoadFileTests(SimpleTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def test_txt_file_is_loaded_with_metadata(self):
        path = self.folder / "notes.txt"
        path.write_text("Windenergie in Deutschland", encoding="utf-8")

        documents = load_file(TextLoader, [path], encoding="utf-8")

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].page_content, "Windenergie in Deutschland")
        self.assertEqual(documents[0].metadata["source"], str(path))
        self.assertEqual(documents[0].metadata["file_name"], "notes.txt")
        self.assertEqual(documents[0].metadata["extension"], ".txt")

    def test_multiple_files_are_concatenated_in_order(self):
        paths = []
        for name in ("a.txt", "b.txt"):
            path = self.folder / name
            path.write_text(name, encoding="utf-8")
            paths.append(path)
        documents = load_file(TextLoader, paths, encoding="utf-8")
        self.assertEqual([d.metadata["file_name"] for d in documents], ["a.txt", "b.txt"])

    def test_no_files_returns_empty_list(self):
        self.assertEqual(load_file(TextLoader, []), [])

    def test_load_all_documents_missing_folder_returns_none(self):
        self.assertIsNone(load_all_documents(self.folder / "missing", file_types=["txt"]))

    def test_load_all_documents_reads_txt_files(self):
        (self.folder / "x.txt").write_text("content", encoding="utf-8")
        documents = load_all_documents(self.folder, file_types=["txt"])
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].metadata["file_name"], "x.txt")
