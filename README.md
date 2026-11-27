# Wind Repowering Knowledge Store

A Django web application that answers the question of an advisory team:

> **Where is the repowering potential in northern Germany** (Schleswig-Holstein, Hamburg, Bremen,
> Niedersachsen, Mecklenburg-Vorpommern)? **Which onshore wind turbines are older than 20 years
> on 31.12.2026, from which manufacturers and with what capacity?**

It loads all German wind turbines from the official **Marktstammdatenregister (MaStR)** of the
Bundesnetzagentur, cleans them, stores them in a SQL database and answers questions with
traceable SQL queries — every answer shows its source, data date and licence. A chat assistant
answers explanatory questions from documentation (RAG), always with citations.

---

## Contents

1. [What the application does](#what-the-application-does)
2. [How it works](#how-it-works)
3. [Technologies and what they are used for](#technologies-and-what-they-are-used-for)
4. [Project structure](#project-structure)
5. [Configuration (`.env`)](#configuration-env)
6. [Option A: Run with Docker](#option-a-run-with-docker)
7. [Option B: Run locally with a virtual environment](#option-b-run-locally-with-a-virtual-environment)
8. [Docker or virtual environment?](#docker-or-virtual-environment)
9. [Pages](#pages)
10. [Data quality: cleaning before import](#data-quality-cleaning-before-import)
11. [Logging](#logging)
12. [Tests](#tests)
13. [Data source, licence and notes](#data-source-licence-and-notes)
14. [AI tool disclosure](#ai-tool-disclosure)

---

## What the application does

| Part | What it offers |
|---|---|
| **Dashboard** (`/`) | Free exploration of all imported turbines: filters for commissioning date range, federal states, operating status and onshore/offshore; key figures, map, turbines by wind type and status (cards or charts), capacity and count by manufacturer (chart or table), commissionings per year. |
| **Repowering-Analyse** (`/fragen/`) | Answers the lead question with **fixed, reviewed SQL questions** (reference date 31.12.2026, onshore, in operation, older than 20 years, northern states). Each answer: chart or table, CSV download, map of the evaluated turbines and a source box (MaStR, data date, licence DL-DE-BY 2.0, number of turbines). The questions and their SQL are stored in the database and managed in Django Admin. |
| **Abfrage vorschlagen** (`/abfrage-vorschlagen/`) | Users suggest new questions; a developer reviews them and adds an approved SQL question in Django Admin. |
| **Chat assistant** | Answers questions such as "Wie aktuell sind die Daten?" from indexed documents only, with document/page citations. Says so when it has no matching context instead of inventing an answer. It never calculates turbine numbers — numbers always come from SQL. |
| **Data pipeline** | Downloads the MaStR export, checks it against the official MaStR documentation (XSD), cleans every row and imports it — all-or-nothing, with a report of every correction. |
| **Daily refresh** | Optional: downloads and imports new MaStR data every day at 03:00 (Europe/Berlin). |

---

## How it works

```
 MaStR Gesamtdatenexport (XML, daily)
        │  open-mastr: download, decode codes to text
        ▼
 data/data/sqlite/open-mastr.db                 ◄── raw source, reproducible
        │  import_wind_data: XSD check → cleaning → import (one transaction)
        ▼
 Django database (SQLite): windenergy_windturbine
        │
        ├── Dashboard ............ Django ORM, free filters
        └── Repowering-Analyse ... SQL questions on the view v_repowering_candidates
                                   (the shared rule: onshore, in operation, dated)

 data/context/*.pdf|*.txt  (documentation)
        │  import_context_documents → import_rag_documents
        ▼
 ChromaDB (vector store) ──► chat: retrieve passages → Groq LLM → answer with citations
```

Turbine numbers and documents are kept strictly apart: the SQL path answers "how many / where /
which", the RAG path explains "why / what does it mean".

---

## Technologies and what they are used for

| Technology | Used for |
|---|---|
| **Python 3.13, Django 5.2** | Web application, data model, admin, management commands |
| **SQLite** | Application database (turbines, SQL questions, suggestions, documents) |
| **open-mastr** | Downloading the MaStR export and turning the XML into a SQLite source database |
| **SQL view `v_repowering_candidates`** | One place for the business rule of the lead question; all catalogue questions read from it |
| **Plotly** (Python) | Charts rendered on the server (bar, donut, stacked bar, line); no custom JavaScript |
| **Folium / Leaflet + CARTO basemap** | Map of turbine locations |
| **Tailwind CSS** (django-tailwind, standalone binary) | Styling of the dashboard; the compiled stylesheet is included |
| **HTMX** | Sending chat messages without reloading the page |
| **Celery + Redis + django-celery-beat** | Daily automatic download and import (scheduler, queue, worker) |
| **sentence-transformers** (`all-MiniLM-L6-v2`) | Turning document text into vectors (embeddings), runs locally |
| **ChromaDB** | Storing and searching those vectors |
| **LangChain** (loaders, text splitter) | Reading PDF/TXT files and splitting them into chunks |
| **Groq** (LLM API) | Writing the chat answer from the retrieved passages |
| **Docker / Docker Compose** | Running everything (web, worker, scheduler, Redis) with one command |
| **Django test framework** | 202 backend tests |

---

## Project structure

```
repowering/            Project settings, URLs, Celery app, shared logging helper
windenergy/            MaStR data: model, import + cleaning, SQL questions, charts, pages
  cleaning.py            data cleansing steps (see below)
  queries.py             runs the stored SQL questions (read-only, with source)
  charts.py              Plotly charts
  management/commands/   download_mastr_wind, import_wind_data
ragapp/                Chat / RAG: document import, embeddings, vector store, answers
theme/                 Tailwind CSS
data/context/          Documents for the chat (PDF/TXT)
data/data/             MaStR downloads and open-mastr database (created at runtime)
tests/                 Backend tests, one folder per app (windenergy, ragapp, repowering)
Dockerfile, compose.yaml
```

---

## Configuration (`.env`)

The API keys are not part of the repository. Copy the template and fill in the keys
(for the review, the keys are sent separately by email):

```powershell
Copy-Item .env.example .env
```

```dotenv
# Map tiles (CARTO)
CARTO_BASEMAP_API_KEY=
# Chat answers (Groq)
API_KEY=
```

Without `CARTO_BASEMAP_API_KEY` the map shows a "key missing" message; without `API_KEY` the
chat is unavailable. Everything else works without keys. Both ways of running (Docker and
virtual environment) read `.env`. **Never commit this file**; it is listed in `.gitignore`.

---

## Option A: Run with Docker

Everything runs in containers: the web app, the Celery worker, the Celery scheduler and Redis.
You only need **Docker Desktop**.

| Container | Role |
|---|---|
| `migrate` | Creates/updates the database tables, then stops |
| `web` | The application on <http://localhost:8000> |
| `worker` | Runs the download + import task |
| `beat` | Schedules the daily refresh (03:00) |
| `redis` | Queue between `beat` and `worker` (reachable only from this computer) |

### 1. Start

Create `.env` first (see [Configuration](#configuration-env)); the containers read it at start.

```powershell
docker compose up -d --build
```

The first build downloads all libraries and takes several minutes; the image is about 3 GB.
Open <http://localhost:8000>.

### 2. Load data (first time)

The containers start with an empty database. Download and import the MaStR data
(needs internet, takes a few minutes):

```powershell
docker compose run --rm web python manage.py download_mastr_wind
docker compose run --rm web python manage.py import_wind_data
```

### 3. Admin user (for managing SQL questions and suggestions)

```powershell
docker compose run --rm web python manage.py createsuperuser
```

### 4. Chat documents (optional)

Put PDF/TXT files into `data/context` on your computer (this folder is shared with the
containers), then:

```powershell
docker compose run --rm web python manage.py import_context_documents
docker compose run --rm web python manage.py import_rag_documents
```

The embedding model is downloaded once and kept.

### Everyday commands

```powershell
docker compose ps                       # status of all containers
docker compose logs -f web              # follow the log of one container
docker compose run --rm web python manage.py test   # run the tests in the container
docker compose up -d --build            # after code changes: rebuild and restart
docker compose down                     # stop (data is kept)
docker compose down -v                  # stop AND delete all data volumes
```

### Where Docker keeps the data

Data lives in Docker volumes, not in the image and not in the project folder, so it survives
restarts and rebuilds: database, MaStR downloads, logs, vector store, open-mastr files and the
embedding model. The image itself contains only code and libraries — **no data and no API keys**.

---

## Option B: Run locally with a virtual environment

You need **Python 3.13** (tested). Commands are for Windows PowerShell in the project folder.

### 1. Create the virtual environment and install packages

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks `Activate.ps1`, call the environment's Python directly, for example
`.\.venv\Scripts\python.exe manage.py runserver`.

### 2. Create the database

```powershell
python manage.py migrate
python manage.py createsuperuser
```

The migration creates all tables, the SQL view, the starter questions Q1–Q6 and the daily
refresh schedule. The database file is `django.sqlite3` in the project folder.

### 3. Load data

```powershell
python manage.py download_mastr_wind      # optional if data/data/sqlite/open-mastr.db exists
python manage.py import_wind_data
```

`download_mastr_wind` accepts `--date today` (default) or a date as `YYYYMMDD`.

### 4. Start the web app

```powershell
python manage.py runserver
```

Open <http://127.0.0.1:8000>. Admin: <http://127.0.0.1:8000/admin/>.

### 5. Chat documents (optional)

```powershell
python manage.py import_context_documents
python manage.py import_rag_documents
```

### 6. Daily refresh (optional)

Needs Redis. The easiest way is to start only the Redis container, then the worker and the
scheduler in two more terminals:

```powershell
docker compose up -d redis
celery -A repowering worker -l INFO --pool=solo
celery -A repowering beat -l INFO
```

`--pool=solo` is needed on Windows, where Celery's default worker mode is not supported.

### Styling (only when templates change)

The compiled stylesheet is included. After changing CSS classes in templates, rebuild it:

```powershell
python manage.py tailwind install   # once: downloads the standalone Tailwind binary
python manage.py tailwind build
```

---

## Docker or virtual environment?

|  | **Docker** | **Virtual environment** |
|---|---|---|
| Install | Docker Desktop only | Python 3.13 + `pip install -r requirements.txt` |
| Start | `docker compose up -d --build` | `python manage.py runserver` |
| Daily refresh | included (worker, beat, Redis) | start Redis, worker and beat yourself |
| Database | Docker volume | `django.sqlite3` in the project folder |
| Best for | demo, other computers, later hosting | development, debugging, quick test runs |

The same code runs in both; only the configuration differs. **The two setups do not share
data** — each has its own database.

---

## Pages

| URL | Page |
|---|---|
| `/` | Dashboard |
| `/fragen/` | Repowering-Analyse (SQL questions, CSV export) |
| `/abfrage-vorschlagen/` | Suggest a new question |
| `/admin/` | Manage SQL questions ("Katalogfragen"), suggestions and users |

---

## Data quality: cleaning before import

The source cannot be expected to be clean, so `import_wind_data` checks every row before
anything is saved (`windenergy/cleaning.py`):

| Step | Check | If it fails |
|---|---|---|
| 1 | Our field list matches the official MaStR documentation (XSD) | warning in the log |
| 2 | All expected columns exist in the source | import stops, nothing is saved |
| 3 | MaStR number present and "SEE" + 12 digits | row rejected |
| 4 | MaStR number not seen before in this export | row rejected (first one kept) |
| 5 | More than the MaStR number is filled | row rejected |
| 6 | Text standardised: Unicode, control/invisible characters and emoji removed, spaces unified, trimmed | corrected and reported |
| 7 | Number, date and date-time as defined in the XSD | value emptied and reported |
| 8 | Catalogue values (state, status, wind type) are known | value emptied and reported |
| 9 | Text fits the database column | cut and reported |
| 10 | Required fields per XSD are present | reported, row kept |
| 11 | Report | every correction and rejection is written to a CSV next to the import log |

The whole import runs in **one transaction**: if anything fails, nothing from that run is saved
and the previous data stays intact.

---

## Logging

Logging is configured in one place, `repowering/settings.py` (`LOGGING`). Code only calls
`logging.getLogger(__name__)`.

| Area | File |
|---|---|
| MaStR download (incl. open-mastr) | `logs/downloads/download_mastr_wind.log` |
| MaStR import | `logs/importing/import_wind_data.log` (+ `*-issues.csv` per run) |
| Chat / RAG | `logs/rag/ragapp.log` |
| Everything else (web app) | `logs/app/windenergy.log` and the console |

Each command run is marked with `STARTED`, `SUCCEEDED` or `FAILED`. While tests run, nothing is
written to log files.

---

## Tests

202 backend tests in `tests/`, one folder per app:

```powershell
python manage.py test                                   # virtual environment
docker compose run --rm web python manage.py test       # Docker
```

They cover the cleaning steps, the import (including rollback and rejected rows), the SQL
questions and their safety rules (read-only), the dashboard calculations, the endpoints (map,
CSV, chat), the scheduled task, the RAG pipeline and the logging configuration. They use
temporary databases and folders, no network and no model downloads; your data is never touched.

---

## Data source, licence and notes

- **Source:** Bundesnetzagentur, Marktstammdatenregister (MaStR), Gesamtdatenexport —
  Datenlizenz Deutschland – Namensnennung – Version 2.0 (DL-DE-BY 2.0).
- **Not in the repository:** downloaded MaStR data, databases, logs, the vector store and `.env`.
  They are created at runtime or by you.
- **Age rule:** the Repowering-Analyse uses the commissioning date of the unit; the EEG funding
  end depends on the EEG commissioning date, which can differ (see `IMPROVEMENTS.txt`).
- **Development settings:** `DEBUG` is on and the secret key is a development key. Change both
  before deploying anywhere public.
- Known data issues and planned improvements are listed in `IMPROVEMENTS.txt`.

---

## AI tool disclosure

**Claude Code** (Anthropic) was used throughout this project as a coding assistant: analysing the
task and the MaStR data, implementing features (data cleaning, SQL catalogue, charts, logging,
Docker setup), writing the backend tests and drafting documentation including this README.
The developer defined the requirements, the business logic and the project structure, made the
design decisions, reviewed and tested the results and corrected the assistant where needed.

Inside the application, AI is used only in the chat assistant: a local embedding model
(`all-MiniLM-L6-v2`) finds matching document passages, and a Groq-hosted language model writes
the answer from those passages, with citations. Turbine numbers are always calculated with SQL,
never by the language model.
