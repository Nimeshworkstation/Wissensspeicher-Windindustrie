import sys

from django.apps import AppConfig


class RagappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ragapp"

    def ready(self):
        # The RAG pipeline prints progress symbols such as "✓". A Windows console
        # (cp1252) cannot encode them, and print() would raise and abort indexing
        # or a chat answer. Replace unprintable characters instead of failing.
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(errors="replace")
            except (AttributeError, ValueError):
                pass  # stream does not support reconfigure (e.g. redirected)
