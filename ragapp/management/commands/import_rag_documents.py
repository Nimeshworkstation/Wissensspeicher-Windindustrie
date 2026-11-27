import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ragapp.models import IndexedFile
from repowering.logging_utils import log_run

logger = logging.getLogger(__name__)   # -> logs/rag/ragapp.log (settings.LOGGING)


class Command(BaseCommand):
    help = "Index every document stored in the Django database into ChromaDB."

    def handle(self, *args, **options):
        log_file = settings.LOG_FILES["rag"]
        self.stdout.write(f"Indexing database documents; log: {log_file}")
        try:
            with log_run(logger, "import_rag_documents"):
                self.index_pending_documents(log_file)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"RAG import failed: {exc}. See log: {log_file}") from exc

    def index_pending_documents(self, log_file):
        from ragapp.tasks import TO_INDEX, _index_record

        records = list(IndexedFile.objects.filter(status__in=TO_INDEX).order_by("pk"))
        logger.info("Found %d database document(s)", len(records))
        if not records:
            logger.info("No pending database documents to index")
            self.stdout.write(self.style.SUCCESS("No pending documents found in the database."))
            return

        from ragapp.src.embeddings import EmbeddingManager
        from ragapp.src.vectorstore_chromadb import ChromaVectorStore

        indexed = failed = total_chunks = 0
        embeddings = EmbeddingManager()
        store = ChromaVectorStore(persist_directory=str(settings.CHROMA_PATH))
        for record in records:
            name = record.path
            logger.info("Indexing %s", name)
            try:
                chunks = _index_record(record, embeddings, store)
                indexed += 1
                total_chunks += chunks
                logger.info("Indexed %s (%d chunks)", name, chunks)
            except Exception as exc:
                failed += 1
                record.status = "failed"
                record.error = str(exc)
                record.save(update_fields=["status", "error", "updated_at"])
                logger.exception("Indexing failed for %s", name)

        summary = (
            f"Indexed {indexed} database document(s), {failed} failed, "
            f"{total_chunks} chunk(s)."
        )
        logger.info("RESULT: %s", summary)
        if failed:
            raise CommandError(f"{summary} See log: {log_file}")
        self.stdout.write(self.style.SUCCESS(summary))
