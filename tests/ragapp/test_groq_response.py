"""Tests for GenerateGroqResponse with ChatGroq mocked (no network calls)."""

from unittest import mock

from django.test import SimpleTestCase

from ragapp.src.response_models.groq_response import GenerateGroqResponse

CHAT_GROQ = "ragapp.src.response_models.groq_response.ChatGroq"


class GenerateGroqResponseTests(SimpleTestCase):
    def test_missing_api_key_raises(self):
        with mock.patch(CHAT_GROQ) as chat:
            with self.assertRaises(ValueError):
                GenerateGroqResponse(api_key="", model="m")
        chat.assert_not_called()

    def test_missing_model_raises(self):
        with mock.patch(CHAT_GROQ):
            with self.assertRaises(ValueError):
                GenerateGroqResponse(api_key="key", model="")

    def test_init_configures_chat_groq(self):
        with mock.patch(CHAT_GROQ) as chat:
            GenerateGroqResponse(api_key="key", model="m")
        chat.assert_called_once_with(api_key="key", model="m", temperature=0.1, max_tokens=1024)

    def test_chat_groq_init_error_becomes_runtime_error(self):
        with mock.patch(CHAT_GROQ, side_effect=Exception("bad")):
            with self.assertRaises(RuntimeError):
                GenerateGroqResponse(api_key="key", model="m")

    def test_empty_prompt_raises(self):
        with mock.patch(CHAT_GROQ):
            llm = GenerateGroqResponse(api_key="key", model="m")
            with self.assertRaises(ValueError):
                llm.generate_answer("")

    def test_generate_answer_returns_content(self):
        with mock.patch(CHAT_GROQ) as chat:
            chat.return_value.invoke.return_value = mock.Mock(content="The answer")
            llm = GenerateGroqResponse(api_key="key", model="m")
            self.assertEqual(llm.generate_answer("prompt"), "The answer")
        chat.return_value.invoke.assert_called_once_with("prompt")

    def test_generate_answer_detail_returns_dict(self):
        with mock.patch(CHAT_GROQ) as chat:
            chat.return_value.invoke.return_value = mock.Mock(content="A")
            llm = GenerateGroqResponse(api_key="key", model="m")
            output = llm.generate_answer("p", detail=True, sources=["s"])
        self.assertEqual(output, {"answer": "A", "sources": ["s"], "confidence": "", "context": ""})

    def test_invoke_error_becomes_runtime_error(self):
        with mock.patch(CHAT_GROQ) as chat:
            chat.return_value.invoke.side_effect = Exception("timeout")
            llm = GenerateGroqResponse(api_key="key", model="m")
            with self.assertRaises(RuntimeError):
                llm.generate_answer("p")
