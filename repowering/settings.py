"""Settings for the Repowering dashboard."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

env_file = BASE_DIR / ".env"
if env_file.is_file():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        if separator:
            value = value.strip().strip("\"'")
            os.environ.setdefault(name.strip(), value)

SECRET_KEY = "local-development-key-change-before-deployment"
DEBUG = True
# Docker can add hosts via DJANGO_ALLOWED_HOSTS (comma-separated); default unchanged.
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tailwind",
    "django_celery_beat",
    "theme",
    "windenergy",
    "ragapp.apps.RagappConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "repowering.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "repowering.wsgi.application"
ASGI_APPLICATION = "repowering.asgi.application"

# Application database. Docker stores it in a volume via SQLITE_PATH; default unchanged.
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": os.environ.get("SQLITE_PATH") or BASE_DIR / "django.sqlite3",
}}
# Source database used by the import_wind_data management command.
OPEN_MASTR_DB = BASE_DIR / "data" / "data" / "sqlite" / "open-mastr.db"
CARTO_BASEMAP_API_KEY = os.environ.get("CARTO_BASEMAP_API_KEY", "").strip()

# RAG application settings. Context documents (PDF/TXT) are placed in data/context.
# Step 1: import_context_documents stores them in the Django database.
# Step 2: import_rag_documents embeds them into the Chroma vector store.
GROQ_API_KEY = (os.environ.get("GROQ_API_KEY") or os.environ.get("API_KEY", "")).strip()
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b").strip()
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "3"))
IMPORT_FOLDER = BASE_DIR / "data" / "context"
CHROMA_PATH = BASE_DIR / "ragapp" / "store" / "vector_store" / "chromadb"
RAG_LOG_DIR = BASE_DIR / "logs" / "rag"

LANGUAGE_CODE = "de-de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
TAILWIND_APP_NAME = "theme"
TAILWIND_USE_STANDALONE_BINARY = True

# The wind turbine admin can submit large selections for bulk actions.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10_000

# Celery requires a running Redis broker. Override this in .env if Redis uses
# a different host, port, or database.
CELERY_BROKER_URL = os.environ.get(
    "CELERY_BROKER_URL", "redis://127.0.0.1:6379/0"
).strip()
CELERY_RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND", CELERY_BROKER_URL
).strip()
CELERY_TIMEZONE = TIME_ZONE
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# --- Logging ---------------------------------------------------------------
# All logging is configured here. Code only calls logging.getLogger(__name__);
# the module path decides where a message is written:
#   windenergy.management.commands.download_mastr_wind -> logs/downloads/download_mastr_wind.log
#   open-MaStR (the download library)                  -> logs/downloads/download_mastr_wind.log
#   windenergy.management.commands.import_wind_data    -> logs/importing/import_wind_data.log
#   windenergy (everything else, e.g. views)            -> logs/app/windenergy.log + console
#   ragapp (commands, tasks, RAG pipeline, views)      -> logs/rag/ragapp.log
# Every command run is marked with STARTED / SUCCEEDED / FAILED
# (repowering/logging_utils.py). While tests run, nothing is written to files.
LOG_DIR = BASE_DIR / "logs"
RUNNING_TESTS = len(sys.argv) > 1 and sys.argv[1] == "test"
LOG_FILES = {
    "app": LOG_DIR / "app" / "windenergy.log",
    "downloads": LOG_DIR / "downloads" / "download_mastr_wind.log",
    "importing": LOG_DIR / "importing" / "import_wind_data.log",
    "rag": RAG_LOG_DIR / "ragapp.log",
}


def _file_handler(path):
    if RUNNING_TESTS:
        return {"class": "logging.NullHandler"}
    path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "class": "logging.FileHandler",
        "filename": path,
        "encoding": "utf-8",
        "delay": True,            # the file is only opened when something is logged
        "formatter": "standard",
    }


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": (
            {"class": "logging.NullHandler"} if RUNNING_TESTS
            else {"class": "logging.StreamHandler", "formatter": "standard"}
        ),
        "app_file": _file_handler(LOG_FILES["app"]),
        "downloads_file": _file_handler(LOG_FILES["downloads"]),
        "importing_file": _file_handler(LOG_FILES["importing"]),
        "rag_file": _file_handler(LOG_FILES["rag"]),
    },
    "loggers": {
        "windenergy": {"handlers": ["console", "app_file"], "level": "INFO", "propagate": False},
        "windenergy.management.commands.download_mastr_wind": {
            "handlers": ["downloads_file"], "level": "INFO", "propagate": False,
        },
        "open-MaStR": {"handlers": ["downloads_file"], "level": "INFO", "propagate": False},
        "windenergy.management.commands.import_wind_data": {
            "handlers": ["importing_file"], "level": "INFO", "propagate": False,
        },
        "ragapp": {"handlers": ["rag_file"], "level": "INFO", "propagate": False},
    },
}
