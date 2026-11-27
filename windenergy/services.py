"""Dashboard chatbot adapter for answers grounded in indexed RAG documents."""


def get_chatbot_reply(message):
    """Return an answer and its citations from the RAG application."""
    from ragapp.services import answer_question

    return answer_question(message)
