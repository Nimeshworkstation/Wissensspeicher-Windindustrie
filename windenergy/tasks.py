import subprocess
import sys

from celery import shared_task
from django.conf import settings
from django.core.management import call_command


@shared_task(name="windenergy.refresh_mastr_wind_data")
def refresh_mastr_wind_data():
    """Download the latest MaStR wind export, then import it into Django."""
    # Run open-mastr in a child process because its logging setup configures the
    # global Python logger. Keeping it isolated preserves the Celery worker log.
    subprocess.run(
        [
            sys.executable,
            str(settings.BASE_DIR / "manage.py"),
            "download_mastr_wind",
        ],
        cwd=settings.BASE_DIR,
        check=True,
    )
    call_command("import_wind_data")
    return "MaStR wind data downloaded and imported."
