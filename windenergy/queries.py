"""Executor for the query catalogue.

The questions and their SQL are stored in the database (model CatalogQuestion)
and managed in Django admin. The database only stores them; this module decides
how they are run:

1. load the question,
2. check that it is a single SELECT/WITH statement,
3. insert the placeholders ({base_filter}, {states}) and run it with
   parameters on a read-only connection state,
4. return rows plus source information.

Note: ``gross_capacity_mw`` contains kW (open-mastr ``grossCapacity``),
so the starter queries divide by 1000 to report MW.
"""

import re
from datetime import date, datetime

from django.db import DatabaseError, connection

from windenergy.models import CatalogQuestion, WindTurbine


DEFAULT_REFERENCE_DATE = date(2026, 12, 31)
SOURCE_NAME = (
    "Bundesnetzagentur, Marktstammdatenregister (MaStR), Gesamtdatenexport"
)
SOURCE_LICENSE = "Datenlizenz Deutschland – Namensnennung – Version 2.0 (DL-DE-BY 2.0)"
SOURCE_URL = "https://www.marktstammdatenregister.de/MaStR/Datendownload"
PAGE_ROW_LIMIT = 250

# Inserted for {base_filter}: selected states and commissioned on or before the cut-off.
BASE_FILTER = """state IN ({states})
  AND commissioning_date <= %(cutoff)s"""


class QueryError(Exception):
    """A catalogue query could not be run; the message is shown to the user."""


def active_questions():
    return CatalogQuestion.objects.filter(is_active=True)


def years_before(value, years):
    try:
        return value.replace(year=value.year - years)
    except ValueError:  # 29 February
        return value.replace(year=value.year - years, day=28)


def build_parameters(reference_date, states):
    """Return the SQL parameters for one run of the catalogue."""
    age = WindTurbine.MIN_REPOWERING_AGE_YEARS
    params = {
        "reference_date": reference_date.isoformat(),
        "cutoff": years_before(reference_date, age).isoformat(),
        "horizon": years_before(reference_date, age - 5).isoformat(),
    }
    for index, state in enumerate(states):
        params[f"state_{index}"] = state
    return params


def check_select_only(sql):
    """Allow exactly one SELECT/WITH statement."""
    statement = sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^(select|with)\b", statement):
        raise QueryError("Nur SELECT- oder WITH-Abfragen sind erlaubt.")
    if ";" in statement:
        raise QueryError("Bitte nur eine einzelne Abfrage ohne Semikolon speichern.")
    return statement


def render_sql(sql_text, states):
    """Insert the placeholders and protect literal % signs (e.g. LIKE 'E-%')."""
    placeholders = ", ".join(f"%(state_{i})s" for i in range(len(states)))
    sql = sql_text.replace("{base_filter}", BASE_FILTER)
    sql = sql.replace("{states}", placeholders)
    # A single % that is not a parameter like %(cutoff)s must be doubled for the DB driver.
    return re.sub(r"%(?!\(|%)", "%%", sql)


def display_sql(sql, params):
    """Readable SQL with the parameter values inserted (display only)."""
    shown = sql
    for name, value in sorted(params.items(), key=lambda item: -len(item[0])):
        shown = shown.replace(f"%({name})s", "'" + str(value).replace("'", "''") + "'")
    return shown.replace("%%", "%")


def _fetch(sql, params, read_only=False):
    with connection.cursor() as cursor:
        if read_only and connection.vendor == "sqlite":
            # SQLite refuses any write while query_only is on.
            cursor.execute("PRAGMA query_only = ON")
        try:
            cursor.execute(sql, params)
            columns = [column[0] for column in cursor.description or []]
            return columns, cursor.fetchall()
        finally:
            if read_only and connection.vendor == "sqlite":
                cursor.execute("PRAGMA query_only = OFF")


def data_stand():
    """Latest MaStR download date found in the imported data."""
    _, rows = _fetch(
        "SELECT MAX(source_download_date) FROM windenergy_windturbine "
        "WHERE source_download_date <> ''",
        {},
    )
    raw = rows[0][0] if rows else None
    if not raw:
        return "unbekannt"
    try:
        return datetime.strptime(raw, "%Y%m%d").strftime("%d.%m.%Y")
    except ValueError:
        return raw


def population(states, params):
    """Counts behind every answer: candidates, and units excluded for missing dates."""
    placeholders = ", ".join(f"%(state_{i})s" for i in range(len(states)))
    _, rows = _fetch(
        "SELECT COUNT(*), MIN(commissioning_date) FROM v_repowering_candidates WHERE "
        + BASE_FILTER.replace("{states}", placeholders),
        params,
    )
    candidates, earliest = rows[0]
    _, rows = _fetch(
        "SELECT COUNT(*) FROM windenergy_windturbine "
        "WHERE wind_onshore_or_offshore = 'Windenergie an Land' "
        "AND operational_status = 'In Betrieb' AND commissioning_date IS NULL "
        f"AND state IN ({placeholders})",
        params,
    )
    if isinstance(earliest, str):
        earliest = date.fromisoformat(earliest[:10])
    return {"candidates": candidates, "earliest": earliest,
            "missing_commissioning_date": rows[0][0]}


def run_question(code, reference_date=DEFAULT_REFERENCE_DATE, states=None):
    """Load one catalogue question from the database, run it, add its source."""
    question = active_questions().filter(code=code).first()
    if question is None:
        raise QueryError(f"Frage {code} wurde nicht gefunden oder ist deaktiviert.")
    states = list(states if states is not None else WindTurbine.DEFAULT_STATES)
    if not states:
        raise QueryError("Mindestens ein Bundesland wählen.")

    params = build_parameters(reference_date, states)
    sql = render_sql(check_select_only(question.sql), states)
    try:
        columns, rows = _fetch(sql, params, read_only=True)
    except (DatabaseError, KeyError, ValueError, TypeError) as exc:
        raise QueryError(f"Die Abfrage {code} ist fehlerhaft: {exc}") from exc

    counts = population(states, params)
    return {
        "question": question,
        "columns": columns,
        "rows": rows,
        "sql": sql,
        "sql_display": display_sql(sql, params),
        "params": params,
        "source": {
            "name": SOURCE_NAME,
            "license": SOURCE_LICENSE,
            "url": SOURCE_URL,
            "data_stand": data_stand(),
            "reference_date": reference_date,
            "cutoff": date.fromisoformat(params["cutoff"]),
            "states": states,
            "candidates": counts["candidates"],
            "earliest_commissioning": counts["earliest"],
            "missing_commissioning_date": counts["missing_commissioning_date"],
            "query_updated_at": question.updated_at,
            "executed_at": datetime.now(),
        },
    }
