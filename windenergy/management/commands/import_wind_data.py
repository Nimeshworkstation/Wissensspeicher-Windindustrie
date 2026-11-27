import csv
import logging
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction
from django.utils import timezone

from windenergy.cleaning import (
    SOURCE_COLUMNS,
    check_schema_against_docs,
    clean_row,
)
from windenergy.models import WindTurbine

from repowering.logging_utils import log_run

logger = logging.getLogger(__name__)   # -> logs/importing/ (settings.LOGGING)


UPDATE_FIELDS = (
    "location_mastr_number",
    "state",
    "district",
    "municipality",
    "municipality_key",
    "postal_code",
    "place",
    "latitude",
    "longitude",
    "registration_date",
    "commissioning_date",
    "commissioning_date_at_current_location",
    "final_shutdown_date",
    "system_status",
    "operational_status",
    "energy_source",
    "gross_capacity_mw",
    "net_capacity_mw",
    "manufacturer",
    "technology",
    "model_designation",
    "hub_height_m",
    "rotor_diameter_m",
    "wind_farm_name",
    "wind_onshore_or_offshore",
    "source_last_update",
    "source_download_date",
    "imported_at",
)


class Command(BaseCommand):
    help = "Import or update wind units from the open-MaStR SQLite database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            type=Path,
            default=settings.OPEN_MASTR_DB,
            help="Path to open-mastr.db (defaults to OPEN_MASTR_DB in settings).",
        )
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        with log_run(logger, "import_wind_data"):
            source_path = options["source"].expanduser().resolve()
            batch_size = options["batch_size"]
            if batch_size < 1:
                raise CommandError("--batch-size must be greater than zero.")
            if not source_path.is_file():
                raise CommandError(f"MaStR source database not found: {source_path}")

            logger.info(
                "Import parameters: source=%s batch_size=%s", source_path, batch_size
            )
            # Cleaning step 1: our field schema vs. the official MaStR documentation (XSD).
            docs_directory = source_path.parent.parent / "docs_download"
            docs_zip, mismatches = check_schema_against_docs(docs_directory)
            if docs_zip is None:
                logger.warning("XSD check skipped: no documentation zip in %s", docs_directory)
            elif mismatches:
                for mismatch in mismatches:
                    logger.warning("XSD mismatch: %s", mismatch)
                self.stdout.write(self.style.WARNING(
                    f"{len(mismatches)} difference(s) between cleaning schema and "
                    f"{docs_zip.name}; see the import log."
                ))
            else:
                logger.info("XSD check passed against %s", docs_zip.name)

            source_uri = f"file:{source_path.as_posix()}?mode=ro"
            rejected_count = 0
            issue_counts = Counter()
            all_issues = []
            seen_keys = set()          # cleaning step 4: duplicate MaStR numbers
            imported_count = 0
            batch_number = 0
            imported_at = timezone.now()
            try:
                # closing(): the `with` of sqlite3 only commits; close the file explicitly.
                # transaction.atomic(): all or nothing - if any batch fails, every
                # batch of this run is rolled back and the old data stays intact.
                with closing(sqlite3.connect(source_uri, uri=True)) as source,                         transaction.atomic():
                    source.row_factory = sqlite3.Row
                    # Cleaning step 2: check the structure explicitly. (SQLite would
                    # silently read a missing "column" in double quotes as a text value.)
                    existing = {
                        column[1] for column in source.execute("PRAGMA table_info(units_wind)")
                    }
                    missing = [column for column in SOURCE_COLUMNS if column not in existing]
                    if missing:
                        raise CommandError(
                            "MaStR source table units_wind is missing column(s): "
                            f"{', '.join(missing) if existing else 'the whole table'}. "
                            "Nothing was imported."
                        )
                    column_sql = ", ".join(f'"{column}"' for column in SOURCE_COLUMNS)
                    cursor = source.execute(f"SELECT {column_sql} FROM units_wind")
                    while rows := cursor.fetchmany(batch_size):
                        batch_number += 1
                        logger.info(
                            "RUNNING batch %s (%s rows)", batch_number, len(rows)
                        )
                        objects = []
                        for row in rows:
                            result = clean_row(dict(row), seen_keys)   # steps 3-10
                            all_issues.extend(result.issues)
                            issue_counts.update((i.field, i.code) for i in result.issues)
                            if result.rejected:
                                rejected_count += 1
                                continue
                            objects.append(WindTurbine(**result.values, imported_at=imported_at))
                        try:
                            WindTurbine.objects.bulk_create(
                                objects,
                                batch_size=batch_size,
                                update_conflicts=True,
                                update_fields=UPDATE_FIELDS,
                                unique_fields=("unit_mastr_number",),
                            )
                        except DatabaseError as exc:
                            raise CommandError(
                                f"Could not save import batch {batch_number}: {exc}. "
                                "Nothing from this run was saved (rolled back)."
                            ) from exc
                        imported_count += len(objects)
                        logger.info(
                            "RUNNING progress: %s rows processed", imported_count
                        )
            except sqlite3.Error as exc:
                raise CommandError(
                    f"Could not read the MaStR source database: {exc}"
                ) from exc

            issues_path = self.write_issues(all_issues)   # cleaning step 11: report
            for (field_name, code), count in sorted(issue_counts.items()):
                logger.info("CLEANING %s %s: %s", field_name, code, count)
            message = (
                f"Imported or updated {imported_count:,} wind units from {source_path}. "
                f"Rejected rows: {rejected_count:,}. Cleaning issues: {len(all_issues):,}"
                + (f" (details: {issues_path})." if issues_path else ".")
            )
            logger.info("Import summary: %s", message)
            self.stdout.write(self.style.SUCCESS(message))

    @staticmethod
    def write_issues(issues):
        """Write every correction and rejection to a CSV next to the import log."""
        if not issues:
            return None
        directory = settings.BASE_DIR / "logs" / "importing"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"import_wind_data-{datetime.now():%Y%m%d-%H%M%S}-issues.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["mastr_nummer", "feld", "problem", "rohwert", "detail"])
            for issue in issues:
                writer.writerow([issue.mastr_number, issue.field, issue.code,
                                 issue.raw_value, issue.detail])
        return path
