"""Optional standalone RAG view; the DIS dashboard uses its HTMX chat instead."""

import logging

from django.shortcuts import render

from .services import answer_question

logger = logging.getLogger(__name__)


def home(request):
    result = None
    error = None
    question = ""
    if request.method == "POST":
        question = request.POST.get("question", "").strip()
        if question:
            try:
                result = answer_question(question)
            except Exception:
                logger.exception("RAG question answering failed")
                error = "The document assistant is currently unavailable."
        else:
            error = "Enter a question."
    return render(request, "ragapp/home.html", {
        "result": result,
        "error": error,
        "question": question,
    })
