"""Tests for create_prompt and create_context in ragapp.src.response_models.prompt_utils."""

from django.test import SimpleTestCase

from ragapp.src.response_models.prompt_utils import create_context, create_prompt


class CreatePromptTests(SimpleTestCase):
    def test_empty_context_returns_none(self):
        self.assertIsNone(create_prompt(question="Q?", context=""))

    def test_none_context_returns_none(self):
        self.assertIsNone(create_prompt(question="Q?", context=None))

    def test_blank_question_returns_none(self):
        self.assertIsNone(create_prompt(question="   ", context="some context"))

    def test_prompt_contains_question_and_context(self):
        prompt = create_prompt(question="What is capacity?", context="[1] a.pdf\nCapacity is 5 MW")
        self.assertIn("What is capacity?", prompt)
        self.assertIn("[1] a.pdf\nCapacity is 5 MW", prompt)

    def test_prompt_contains_not_enough_context_instruction(self):
        prompt = create_prompt(question="Q?", context="ctx")
        self.assertIn('say exactly: "I don\'t have enough context."', prompt)

    def test_context_appears_before_question(self):
        prompt = create_prompt(question="QUESTION_MARKER", context="CONTEXT_MARKER")
        self.assertLess(prompt.index("CONTEXT_MARKER"), prompt.index("QUESTION_MARKER"))


class CreateContextTests(SimpleTestCase):
    def test_empty_list_gives_empty_context_and_sources(self):
        self.assertEqual(create_context([]), {"context": "", "sources": []})

    def test_labels_are_numbered_from_one(self):
        docs = [
            {"content": "first", "metadata": {"file_name": "a.txt"}},
            {"content": "second", "metadata": {"file_name": "b.txt"}},
        ]
        result = create_context(docs)
        self.assertEqual(result["context"], "[1] a.txt\nfirst\n\n[2] b.txt\nsecond")
        self.assertEqual([s["citation"] for s in result["sources"]], [1, 2])

    def test_pdf_page_index_is_displayed_one_based(self):
        docs = [{"content": "x", "metadata": {"file_name": "r.pdf", "page": 0}}]
        result = create_context(docs)
        self.assertIn("[1] r.pdf, p. 1\n", result["context"])
        self.assertEqual(result["sources"][0]["page"], 1)

    def test_string_page_is_converted(self):
        docs = [{"content": "x", "metadata": {"file_name": "r.pdf", "page": "9"}}]
        self.assertEqual(create_context(docs)["sources"][0]["page"], 10)

    def test_txt_without_page_has_no_page(self):
        docs = [{
            "content": "x",
            "metadata": {"file_name": "notes.txt", "source": "data/context/notes.txt"},
        }]
        result = create_context(docs)
        self.assertEqual(result["context"], "[1] notes.txt\nx")
        self.assertIsNone(result["sources"][0]["page"])

    def test_source_used_when_file_name_missing(self):
        docs = [{"content": "x", "metadata": {"source": "data/context/s.txt"}}]
        source = create_context(docs)["sources"][0]
        self.assertEqual(source["title"], "data/context/s.txt")
        self.assertEqual(source["source"], "data/context/s.txt")

    def test_unknown_source_fallback(self):
        result = create_context([{"content": "x", "metadata": None}])
        self.assertEqual(result["context"], "[1] Unknown source\nx")
        self.assertEqual(result["sources"][0]["title"], "Unknown source")
        self.assertEqual(result["sources"][0]["source"], "Unknown source")

    def test_source_details_include_full_source_and_score(self):
        docs = [{
            "content": "x",
            "metadata": {"file_name": "r.pdf", "source": "data/context/r.pdf", "page": 2},
            "similarity_score": 0.75,
        }]
        self.assertEqual(
            create_context(docs)["sources"][0],
            {"citation": 1, "title": "r.pdf", "source": "data/context/r.pdf",
             "page": 3, "similarity_score": 0.75},
        )

    def test_missing_content_becomes_empty_text(self):
        result = create_context([{"metadata": {"file_name": "a.txt"}}])
        self.assertEqual(result["context"], "[1] a.txt\n")
