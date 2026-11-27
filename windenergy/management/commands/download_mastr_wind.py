import logging
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from repowering.logging_utils import log_run
from windenergy.open_mastr_logging import capture_open_mastr_logs

logger = logging.getLogger(__name__)   # -> logs/downloads/ (settings.LOGGING)


class Command(BaseCommand):
    help = "Download the wind data export from the Marktstammdatenregister."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            default="today",
            help="Download date: 'today' or a date in YYYYMMDD format (default: today).",
        )
        parser.add_argument(
            "--output-dir",
            type=Path,
            default=settings.BASE_DIR / "data",
            help="open-MaStR output directory (default: the project's data folder).",
        )

    def handle(self, *args, **options):
        with log_run(logger, "download_mastr_wind"):
            selected_date = options["date"].strip()
            if selected_date != "today":
                try:
                    datetime.strptime(selected_date, "%Y%m%d")
                except ValueError as exc:
                    raise CommandError(
                        "--date must be 'today' or a valid date in YYYYMMDD format."
                    ) from exc

            output_dir = options["output_dir"].expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            mastr_home = settings.BASE_DIR / ".open_mastr"

            logger.info(
                "Download parameters: date=%s data=wind output_dir=%s "
                "bulk_cleansing=True english=True keep_old_downloads=True",
                selected_date,
                output_dir,
            )
            self.stdout.write(
                f"Downloading MaStR wind data for {selected_date} to {output_dir}..."
            )
            try:
                with capture_open_mastr_logs(logger.handlers, mastr_home) as Mastr:
                    mastr = Mastr(engine="sqlite", output_dir=str(output_dir))
                    mastr.download(
                        data="wind",
                        date=selected_date,
                        bulk_cleansing=True,
                        english=True,
                        keep_old_downloads=True,
                    )
            except ImportError as exc:
                raise CommandError(
                    "The open-mastr package is required. Install it with: "
                    "python -m pip install open-mastr"
                ) from exc
            except Exception as exc:
                raise CommandError(f"MaStR wind data download failed: {exc}") from exc

            self.stdout.write(
                self.style.SUCCESS(
                    "Download complete. Next, run: python manage.py import_wind_data"
                )
            )
