"""Step 1 of the RAG pipeline: store the context documents in the Django database.

Reads every PDF/TXT file in settings.IMPORT_FOLDER (data/context) and saves its
bytes in IndexedFile:
- new file         -> created with status "pending"
- changed content  -> bytes replaced, status set back to "pending"
- unchanged        -> left as it is

Step 2 is `python manage.py import_rag_documents`, which embeds every pending
document into the Chroma vector store.
"""

import hashlib
import logging
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ragapp.models import IndexedFile
from repowering.logging_utils import log_run

logger = logging.getLogger(__name__)   # -> logs/rag/ragapp.log (settings.LOGGING)

SUPPORTED_SUFFIXES = {".pdf", ".txt"}


class Command(BaseCommand):
    help = "Store the PDF/TXT context documents from data/context in the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--folder",
            type=Path,
            default=settings.IMPORT_FOLDER,
            help="Folder with the context documents (default: IMPORT_FOLDER = data/context).",
        )

    def handle(self, *args, **options):
        folder = options["folder"].expanduser().resolve()
        log_file = settings.LOG_FILES["rag"]
        try:
            with log_run(logger, "import_context_documents", folder=folder):
                if not folder.is_dir():
                    raise CommandError(f"Context folder not found: {folder}")

                created = updated = unchanged = skipped = 0
                seen_paths = set()
                for file_path in sorted(folder.iterdir()):
                    if not file_path.is_file():
                        continue
                    if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
                        skipped += 1
                        logger.info("SKIPPED: %s (only PDF and TXT are supported)", file_path.name)
                        self.stdout.write(f"  skipped   {file_path.name} (only PDF/TXT)")
                        continue

                    content = file_path.read_bytes()
                    content_hash = hashlib.sha256(content).hexdigest()
                    # Stored relative to the project, so the record is the same on every machine.
                    try:
                        stored_path = file_path.relative_to(settings.BASE_DIR).as_posix()
                    except ValueError:
                        stored_path = file_path.as_posix()
                    seen_paths.add(stored_path)

                    record = IndexedFile.objects.filter(path=stored_path).first()
                    if record is None:
                        IndexedFile.objects.create(
                            path=stored_path,
                            content_hash=content_hash,
                            original_file=content,
                            status="pending",
                        )
                        created += 1
                        state = "new"
                    elif record.content_hash != content_hash:
                        record.content_hash = content_hash
                        record.original_file = content
                        record.status = "pending"
                        record.error = ""
                        record.save()
                        updated += 1
                        state = "changed"
                    else:
                        unchanged += 1
                        state = "unchanged"
                    logger.info("%s: %s (%d bytes)", state.upper(), stored_path, len(content))
                    self.stdout.write(f"  {state:<9} {stored_path}")

                missing = IndexedFile.objects.exclude(path__in=seen_paths).filter(
                    path__startswith=_relative_prefix(folder)
                )
                for record in missing:
                    logger.warning("NOT IN FOLDER ANYMORE (kept in database): %s", record.path)
                    self.stdout.write(f"  missing   {record.path} (kept in database)")

                summary = (
                    f"{created} new, {updated} changed, {unchanged} unchanged, "
                    f"{skipped} skipped."
                )
                logger.info("RESULT: %s", summary)
                self.stdout.write(self.style.SUCCESS(f"Context documents stored: {summary}"))
                if created or updated:
                    self.stdout.write("Next, run: python manage.py import_rag_documents")
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"Context import failed: {exc}. See log: {log_file}") from exc


def _relative_prefix(folder):
    try:
        return folder.relative_to(settings.BASE_DIR).as_posix() + "/"
    except ValueError:
        return folder.as_posix() + "/"
