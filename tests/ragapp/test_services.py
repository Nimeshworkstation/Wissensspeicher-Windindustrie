"""Tests for ragapp.services.answer_question (validation, empty store, happy path).

ChromaVectorStore, the embedding manager and GenerateGroqResponse are mocked,
so no model, vector store or network is used.
"""

import tempfile
from unittest import mock

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from ragapp import services

NOT_ENOUGH = {"answer": "I don't have enough context.", "sources": []}


class AnswerQuestionTests(SimpleTestCase):
    def setUp(self):
        services._embedding_manager.cache_clear()
        self.addCleanup(services._embedding_manager.cache_clear)
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        settings_override = override_settings(
            GROQ_API_KEY="test-key", GROQ_MODEL="test-model", RAG_TOP_K=3,
            CHROMA_PATH=tmp.name,
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)

        store_patch = mock.patch("ragapp.src.vectorstore_chromadb.ChromaVectorStore")
        self.store_cls = store_patch.start()
        self.addCleanup(store_patch.stop)
        self.store = self.store_cls.return_value
        self.store.collection.count.return_value = 2

        manager_patch = mock.patch.object(services, "_embedding_manager")
        self.manager_factory = manager_patch.start()
        self.addCleanup(manager_patch.stop)
        self.manager_factory.return_value.generate_embedding.return_value = np.array(
            [[0.1, 0.2, 0.3]]
        )

        groq_patch = mock.patch(
            "ragapp.src.response_models.groq_response.GenerateGroqResponse"
        )
        self.groq_cls = groq_patch.start()
        self.addCleanup(groq_patch.stop)
        self.groq_cls.return_value.generate_answer.return_value = "Wind is strong [1]."

    def test_empty_question_raises(self):
        with self.assertRaises(ValueError):
            services.answer_question("   ")

    def test_top_k_below_one_raises(self):
        with self.assertRaises(ValueError):
            services.answer_question("Question?", top_k=0)

    def test_missing_groq_key_raises(self):
        with override_settings(GROQ_API_KEY=""):
            with self.assertRaises(ValueError):
                services.answer_question("Question?")

    def test_validation_happens_before_store_is_opened(self):
        with self.assertRaises(ValueError):
            services.answer_question("")
        self.store_cls.assert_not_called()

    def test_empty_vector_store_returns_not_enough_context(self):
        self.store.collection.count.return_value = 0
        self.assertEqual(services.answer_question("Question?"), NOT_ENOUGH)
        self.manager_factory.assert_not_called()
        self.groq_cls.assert_not_called()

    def test_no_retrieved_documents_returns_not_enough_context(self):
        self.store.retrieve_documents.return_value = []
        self.assertEqual(services.answer_question("Question?"), NOT_ENOUGH)
        self.groq_cls.assert_not_called()

    def test_happy_path_returns_answer_and_sources(self):
        self.store.retrieve_documents.return_value = [
            {
                "content": "Wind text",
                "metadata": {
                    "file_name": "report.pdf",
                    "source": "data/context/report.pdf",
                    "page": 4,
                },
                "similarity_score": 0.9,
            }
        ]
        result = services.answer_question("  How strong is wind?  ")

        self.assertEqual(result["answer"], "Wind is strong [1].")
        self.assertEqual(
            result["sources"],
            [{
                "citation": 1,
                "title": "report.pdf",
                "source": "data/context/report.pdf",
                "page": 5,
                "similarity_score": 0.9,
            }],
        )

    def test_happy_path_uses_configured_store_embedding_and_llm(self):
        self.store.retrieve_documents.return_value = [
            {"content": "Wind text", "metadata": {"file_name": "report.pdf", "page": 4}}
        ]
        services.answer_question("  How strong is wind?  ")

        self.store_cls.assert_called_once_with(persist_directory=str(settings.CHROMA_PATH))
        self.manager_factory.return_value.generate_embedding.assert_called_once_with(
            ["How strong is wind?"]
        )
        self.groq_cls.assert_called_once_with(api_key="test-key", model="test-model")
        prompt = self.groq_cls.return_value.generate_answer.call_args.kwargs["prompt"]
        self.assertIn("How strong is wind?", prompt)
        self.assertIn("[1] report.pdf, p. 5", prompt)

    def test_default_top_k_comes_from_settings(self):
        self.store.retrieve_documents.return_value = []
        services.answer_question("Question?")
        self.assertEqual(self.store.retrieve_documents.call_args.kwargs["top_k"], 3)

    def test_explicit_top_k_is_passed_to_store(self):
        self.store.retrieve_documents.return_value = []
        services.answer_question("Question?", top_k=7)
        self.assertEqual(self.store.retrieve_documents.call_args.kwargs["top_k"], 7)

    def test_llm_error_propagates(self):
        self.store.retrieve_documents.return_value = [{"content": "x", "metadata": {}}]
        self.groq_cls.return_value.generate_answer.side_effect = RuntimeError("down")
        with self.assertRaises(RuntimeError):
            services.answer_question("Question?")


class EmbeddingManagerCacheTests(SimpleTestCase):
    def setUp(self):
        services._embedding_manager.cache_clear()
        self.addCleanup(services._embedding_manager.cache_clear)

    def test_embedding_manager_is_created_once(self):
        with mock.patch("ragapp.src.embeddings.EmbeddingManager") as manager_cls:
            first = services._embedding_manager()
            second = services._embedding_manager()
        self.assertIs(first, second)
        manager_cls.assert_called_once_with()
