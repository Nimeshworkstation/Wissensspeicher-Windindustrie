import csv
from datetime import date, datetime
import logging
from urllib.parse import urlencode

import folium
from django.conf import settings
from django.contrib import messages
from django.db.models import Case, CharField, Count, F, FloatField, Max, Min, Q, Sum, Value, When
from django.db.models.functions import Coalesce, ExtractYear
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET, require_POST

from windenergy.charts import (
    catalog_chart,
    commissioning_line_chart,
    manufacturer_chart,
    plotly_script_tag,
    status_donut,
    status_windtype_chart,
)
from windenergy.models import WindTurbine
from windenergy.forms import QuerySuggestionForm
from windenergy.queries import (
    DEFAULT_REFERENCE_DATE,
    PAGE_ROW_LIMIT,
    QueryError,
    active_questions,
    run_question,
)
from windenergy.services import get_chatbot_reply

logger = logging.getLogger(__name__)


def suggest_query(request):
    form = QuerySuggestionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(
            request,
            "Danke! Ihr Abfragevorschlag wurde gespeichert und wird geprüft.",
        )
        return redirect("query-suggestion")
    return render(request, "windenergy/query_suggestion.html", {"form": form})


def index(request):
    context, error = dashboard_context(request)
    context.update({
        "data_stand_date": latest_data_stand_date(),
        "plotly_script": plotly_script_tag(),
        "results_error": error,
        "chat_questions": [
            "Was bedeuten Von und Bis?",
            "Wie aktuell sind die Daten?",
            "Wie funktionieren die Filter?",
        ],
    })
    return render(request, "windenergy/index.html", context)


def dashboard_context(request):
    minimum = minimum_commissioning_date()
    maximum = maximum_commissioning_date()
    states = selected_states_for(request)
    statuses = selected_statuses_for(request)
    wind_types = selected_wind_types_for(request)
    raw_bis = request.GET.get("bis", "").strip()
    raw_von = request.GET.get("von", "").strip()
    error = ""
    von = minimum
    bis = maximum

    try:
        if raw_von:
            von = date.fromisoformat(raw_von)
        if raw_bis:
            bis = date.fromisoformat(raw_bis)
    except ValueError:
        error = "Bitte gültige Von- und Bis-Daten wählen."

    if not error:
        if von > bis:
            error = "Von darf nicht nach Bis liegen."

    context = {
        "states": WindTurbine.State.values,
        "selected_states": states,
        "statuses": WindTurbine.OperationalStatus.choices,
        "selected_statuses": statuses,
        "wind_types": WindTurbine.WindType.choices,
        "selected_wind_types": wind_types,
        "maximum_commissioning_date": maximum.isoformat(),
        "von_iso": von.isoformat(),
        "von_label": von.strftime("%d.%m.%Y"),
        "bis_iso": bis.isoformat(),
        "bis_label": bis.strftime("%d.%m.%Y"),
        "validation_error": error,
    }
    if error:
        context["results_error"] = error
        return context, error

    missing_commissioning_count = WindTurbine.objects.filter(
        state__in=states,
        commissioning_date__isnull=True,
    ).count() if states else 0

    records = turbines_data(states, von, bis, statuses, wind_types)
    comparison_records = records
    manufacturer_label = Case(
        When(
            Q(manufacturer__isnull=True) | Q(manufacturer=""),
            then=Value(WindTurbine.UNKNOWN_MANUFACTURER),
        ),
        default=F("manufacturer"),
        output_field=CharField(),
    )
    summary = list(records.annotate(manufacturer_label=manufacturer_label)
        .values("manufacturer_label")
        .annotate(
            name=F("manufacturer_label"),
            count=Count("unit_mastr_number", filter=Q(gross_capacity_mw__isnull=False)),
            capacity=Coalesce(
                Sum("gross_capacity_mw"),
                Value(0.0, output_field=FloatField()),
            ),
        )
        .values("name", "count", "capacity")
        .order_by("-capacity", "name"))
    max_capacity = max((item["capacity"] for item in summary), default=0) or 1
    for item in summary:
        item["bar_width"] = max(0, item["capacity"] / max_capacity * 100)
        item["capacity_display"] = german_number(item["capacity"] / 1000, 2)
        item["count_display"] = german_number(item["count"], 0)
    # Second ranking for the "Anzahl nach Hersteller" card: by number of units.
    summary_by_count = sorted(summary, key=lambda item: (-item["count"], item["name"]))
    # Plotly charts rendered in Python (the first one loads the Plotly library).
    chart_count = manufacturer_chart(summary, "count")  # Plotly is loaded in <head>
    chart_capacity = manufacturer_chart(summary, "capacity")

    comparison_rows = list(
        comparison_records.values("operational_status", "wind_onshore_or_offshore")
        .annotate(
            count=Count("unit_mastr_number"),
            capacity=Coalesce(
                Sum("gross_capacity_mw"),
                Value(0.0, output_field=FloatField()),
            ),
        )
        .order_by("operational_status", "wind_onshore_or_offshore")
    )
    status_comparison_records = turbines_data(
        states, von, bis, statuses=None, wind_types=wind_types
    )
    status_comparison_rows = list(
        status_comparison_records.values("operational_status", "wind_onshore_or_offshore")
        .annotate(
            count=Count("unit_mastr_number"),
            capacity=Coalesce(
                Sum("gross_capacity_mw"),
                Value(0.0, output_field=FloatField()),
            ),
        )
    )
    status_grouped = {
        (row["operational_status"], row["wind_onshore_or_offshore"]): row
        for row in status_comparison_rows
    }
    grouped = {
        (row["wind_onshore_or_offshore"], row["operational_status"]): row
        for row in comparison_rows
    }
    comparison_cards = []
    for wind_type, wind_type_label in WindTurbine.WindType.choices:
        status_rows = []
        total_count = 0
        total_capacity = 0.0
        for status, status_label in WindTurbine.OperationalStatus.choices:
            included = wind_type in wind_types and status in statuses
            row = grouped.get((wind_type, status), {}) if included else {}
            count = row.get("count", 0)
            capacity = row.get("capacity", 0.0)
            total_count += count
            total_capacity += capacity
            status_rows.append({
                "label": status_label,
                "included": included,
                "count": count,
                "capacity_mw": capacity / 1000,
                "capacity_display": german_number(capacity / 1000, 2),
            })
        comparison_cards.append({
            "label": wind_type_label,
            "included": wind_type in wind_types,
            "count": total_count,
            "capacity_display": german_number(total_capacity / 1000, 2),
            "statuses": status_rows,
            # Plotly donut: this wind type split by operating status.
            "chart": status_donut(status_rows) if wind_type in wind_types else "",
            "note": (
                "Keine Offshore-Anlagen entsprechen dem gewählten Datums-, Regions- und Statusfilter."
                if wind_type == WindTurbine.WindType.OFFSHORE
                and wind_type in wind_types and total_count == 0
                else ""
            ),
        })

    status_cards = []
    for status, status_label in WindTurbine.OperationalStatus.choices:
        type_rows = []
        total_count = 0
        total_capacity = 0.0
        for wind_type, wind_type_label in WindTurbine.WindType.choices:
            included = wind_type in wind_types
            row = status_grouped.get((status, wind_type), {}) if included else {}
            count = row.get("count", 0)
            capacity = row.get("capacity", 0.0)
            total_count += count
            total_capacity += capacity
            type_rows.append({
                "label": wind_type_label,
                "included": included,
                "count": count,
                "capacity_mw": capacity / 1000,
                "capacity_display": german_number(capacity / 1000, 2),
            })
        status_cards.append({
            "label": status_label,
            "count": total_count,
            "capacity_display": german_number(total_capacity / 1000, 2),
            "wind_types": type_rows,
        })
    # Charts for the "Diagramm" tabs of the status section (cards stay unchanged).
    # Line chart: turbines commissioned per year. Uses the same filtered
    # turbines as the rest of the dashboard; years without turbines count 0.
    per_year = dict(
        records.order_by()
        .annotate(year=ExtractYear("commissioning_date"))
        .values("year")
        .annotate(count=Count("unit_mastr_number"))
        .values_list("year", "count")
    )
    chart_years = list(range(von.year, bis.year + 1))
    commissioning_chart = commissioning_line_chart(
        chart_years, [per_year.get(year, 0) for year in chart_years]
    ) if per_year else ""

    status_charts = {
        "count": status_windtype_chart(status_cards, "count"),
        "capacity": status_windtype_chart(status_cards, "capacity"),
    }

    located_count = records.filter(
        latitude__gte=-90,
        latitude__lte=90,
        longitude__gte=-180,
        longitude__lte=180,
    ).count()
    totals = records.aggregate(
        count=Count("unit_mastr_number"),
        capacity=Coalesce(
            Sum("gross_capacity_mw"),
            Value(0.0, output_field=FloatField()),
        ),
    )
    map_parameters = [("state", state) for state in states]
    if not states:
        map_parameters.append(("state", "__none__"))
    map_parameters.extend(("status", status) for status in statuses)
    if not statuses:
        map_parameters.append(("status", "__none__"))
    map_parameters.extend(("wind_type", wind_type) for wind_type in wind_types)
    if not wind_types:
        map_parameters.append(("wind_type", "__none__"))
    map_parameters.extend((("bis", bis.isoformat()), ("von", von.isoformat())))
    context.update({
        "comparison_cards": comparison_cards,
        "status_cards": status_cards,
        "status_charts": status_charts,
        "commissioning_chart": commissioning_chart,
        "missing_commissioning_count": german_number(missing_commissioning_count, 0),
        "has_missing_commissioning": missing_commissioning_count > 0,
        "results": {
            "count": german_number(totals["count"], 0),
            "capacity": german_number(totals["capacity"] / 1000, 2),
            "mapped": german_number(located_count, 0),
            "manufacturers": summary,
            "manufacturers_by_count": summary_by_count,
            "chart_count": chart_count,
            "chart_capacity": chart_capacity,
            "map_url": f"{reverse('turbine-map')}?{urlencode(map_parameters)}",
        },
        "results_error": "",
    })
    return context, ""


def german_number(value, decimal_places):
    formatted = f"{value:,.{decimal_places}f}"
    return formatted.replace(",", "\0").replace(".", ",").replace("\0", ".")


@require_POST
def chat(request):
    message = request.POST.get("message", "").strip()
    if not message:
        return HttpResponse(status=204)
    message = message[:500]
    try:
        result = get_chatbot_reply(message)
    except Exception:
        logger.exception("RAG chatbot failed to answer a question")
        result = {
            "answer": "Der Assistent ist gerade nicht verfügbar. Bitte versuche es später erneut.",
            "sources": [],
        }
    return render(request, "windenergy/partials/chat_messages.html", {
        "user_message": message,
        "bot_reply": result["answer"],
        "bot_sources": result.get("sources", []),
    })


# The map is embedded in an <iframe> on the dashboard and the analysis page.
# Django's default X-Frame-Options: DENY would make the browser refuse it;
# SAMEORIGIN allows framing by this site only.
@xframe_options_sameorigin
@require_GET
def turbine_map(request):
    """Render the filtered locations as a Folium map document."""
    selected_states = selected_states_for(request)
    selected_statuses = selected_statuses_for(request)
    selected_wind_types = selected_wind_types_for(request)
    date_range = selected_commissioning_range(request)
    if isinstance(date_range, JsonResponse):
        return HttpResponse(date_range.content, status=date_range.status_code, content_type="text/plain")
    commissioning_from, commissioning_to = date_range
    payload = turbines_data(
        selected_states,
        commissioning_from,
        commissioning_to,
        selected_statuses,
        selected_wind_types,
    ).values(
        "latitude",
        "longitude",
        "gross_capacity_mw",
        "manufacturer",
        "model_designation",
        "state",
        "commissioning_date",
    ).iterator(chunk_size=1000)
    api_key = settings.CARTO_BASEMAP_API_KEY
    if not api_key:
        return HttpResponse(
            "CARTO basemap key is missing. Set the CARTO_BASEMAP_API_KEY environment variable.",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    map_view = folium.Map(location=[51.2, 10.4], zoom_start=6, tiles=None)
    folium.TileLayer(
        tiles=(
            "https://basemaps.cartocdn.com/rastertiles/light_all/"
            "{z}/{x}/{y}.png?" + urlencode({"key": api_key})
        ),
        attr=(
            '&copy; <a href="https://www.openstreetmap.org/copyright">'
            'OpenStreetMap</a> contributors, &copy; '
            '<a href="https://carto.com/attributions/">CARTO</a>'
        ),
        name="CARTO Positron",
        control=False,
        max_zoom=20,
    ).add_to(map_view)
    for turbine in payload:
        lat, lon = turbine["latitude"], turbine["longitude"]
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
            continue
        capacity_kw = turbine["gross_capacity_mw"] or 0
        capacity_mw = capacity_kw / 1000
        radius = max(4, min(12, 4 + capacity_mw ** 0.5))
        popup = folium.Popup(
            f"<strong>{_html(turbine['manufacturer'] or WindTurbine.UNKNOWN_MANUFACTURER)}</strong><br>"
            f"{_html(turbine['model_designation'] or '')}<br>"
            f"{_html(turbine['state'] or '')} &middot; {capacity_mw:,.2f} MW<br>"
            f"Inbetriebnahme: {_html(turbine['commissioning_date'] or 'unbekannt')}",
            max_width=300,
        )
        folium.CircleMarker(
            location=[lat, lon], radius=radius, color="#c65f43",
            fill=True, fill_color="#ed7959", fill_opacity=0.75, popup=popup,
        ).add_to(map_view)
    return HttpResponse(map_view.get_root().render(), content_type="text/html; charset=utf-8")


def turbines_data(
    selected_states,
    commissioning_from,
    commissioning_to,
    statuses=None,
    wind_types=None,
):
    """Return turbines within the selected commissioning-date interval."""
    records = WindTurbine.objects.filter(
        commissioning_date__gte=commissioning_from,
        commissioning_date__lte=commissioning_to,
    )
    if not selected_states:
        return records.none()
    if statuses is not None and not statuses:
        return records.none()
    if wind_types is not None and not wind_types:
        return records.none()
    records = records.filter(state__in=selected_states)
    if statuses is not None:
        records = records.filter(operational_status__in=statuses)
    if wind_types is not None:
        records = records.filter(wind_onshore_or_offshore__in=wind_types)
    return records


def selected_states_for(request):
    available_states = tuple(WindTurbine.State.values)
    if "filters_present" in request.GET:
        return [state for state in request.GET.getlist("state") if state in available_states]
    if "state" not in request.GET:
        return list(WindTurbine.DEFAULT_STATES)
    return [state for state in request.GET.getlist("state") if state in available_states]


def selected_statuses_for(request):
    available = tuple(WindTurbine.OperationalStatus.values)
    if "status_filter_present" not in request.GET:
        return list(WindTurbine.DEFAULT_STATUSES)
    return [status for status in request.GET.getlist("status") if status in available]


def selected_wind_types_for(request):
    available = tuple(WindTurbine.WindType.values)
    if "wind_type_filter_present" not in request.GET:
        return list(WindTurbine.DEFAULT_WIND_TYPES)
    return [kind for kind in request.GET.getlist("wind_type") if kind in available]


def selected_commissioning_range(request):
    raw_von = request.GET.get("von", "").strip()
    raw_bis = request.GET.get("bis", "").strip()
    try:
        commissioning_from = date.fromisoformat(raw_von) if raw_von else minimum_commissioning_date()
        commissioning_to = date.fromisoformat(raw_bis) if raw_bis else maximum_commissioning_date()
    except ValueError:
        return JsonResponse({"error": "Bitte gültige Von- und Bis-Daten wählen."}, status=400)
    if commissioning_from > commissioning_to:
        return JsonResponse({"error": "Von darf nicht nach Bis liegen."}, status=400)
    return commissioning_from, commissioning_to


def minimum_commissioning_date():
    """Return the earliest imported commissioning date, or a safe empty-data fallback."""
    return WindTurbine.objects.aggregate(
        earliest=Min("commissioning_date")
    )["earliest"] or date(1900, 1, 1)


def maximum_commissioning_date():
    """Return the latest imported commissioning date, or today when no dates exist."""
    return WindTurbine.objects.aggregate(
        latest=Max("commissioning_date")
    )["latest"] or timezone.localdate()


def latest_data_stand_date():
    """Format the latest MaStR export date recorded on imported turbine rows."""
    raw_date = (
        WindTurbine.objects.exclude(source_download_date="")
        .order_by("-source_download_date")
        .values_list("source_download_date", flat=True)
        .first()
    )
    if not raw_date:
        return "unbekannt"
    try:
        return datetime.strptime(raw_date, "%Y%m%d").strftime("%d.%m.%Y")
    except ValueError:
        return raw_date


def years_after(value, years):
    try:
        return value.replace(year=value.year + years)
    except ValueError:  # 29 February in a leap year
        return value.replace(year=value.year + years, day=28)


def _html(value):
    """Escape database strings inserted into Folium popup markup."""
    import html
    return html.escape(str(value), quote=True)


# --- Query catalogue ("Repowering-Analyse") --------------------------------
# Questions and their SQL are stored in the database (CatalogQuestion) and
# managed in Django admin; windenergy/queries.py runs them.


def _catalog_parameters(request):
    """Fixed cut-off date (31.12.2026); states limited to the five northern states."""
    error = ""
    reference_date = DEFAULT_REFERENCE_DATE
    if "states_present" in request.GET:
        states = [
            state for state in request.GET.getlist("state")
            if state in WindTurbine.DEFAULT_STATES
        ]
    else:
        states = list(WindTurbine.DEFAULT_STATES)
    if not states:
        error = "Bitte mindestens ein Bundesland wählen."
    return reference_date, states, error


def _chart_unit(column):
    """Unit for the bar labels, derived from the value column's name."""
    name = (column or "").lower()
    if name.endswith("_mw"):
        return "MW"
    if name.endswith("_prozent"):
        return "%"
    if name.endswith("_m"):
        return "m"
    return ""  # counts such as "anlagen" have no unit


def _catalog_chart(result):
    """Chart data for the columns named in admin, plus hints when that fails.

    Returns (bars, hints). bars is empty when no chart can be drawn; hints
    explain why, so a mistake in admin does not make the chart vanish silently.
    """
    question = result["question"]
    columns = result["columns"]
    label_column = (question.chart_label or "").strip()
    value_column = (question.chart_value or "").strip()
    if not label_column and not value_column:
        return [], []  # no chart configured: table only, nothing to explain
    available = ", ".join(columns)
    if not label_column or not value_column:
        return [], [
            "Diagramm nicht möglich: In Django-Admin müssen Beschriftungsspalte "
            f"und Wertespalte gesetzt sein. Verfügbare Spalten: {available}."
        ]
    missing = [name for name in (label_column, value_column) if name not in columns]
    if missing:
        names = ", ".join(f"„{name}“" for name in missing)
        return [], [
            f"Diagramm nicht möglich: Spalte {names} ist nicht im Ergebnis. "
            f"Verfügbare Spalten: {available}."
        ]
    if not result["rows"]:
        return [], []
    label_index = columns.index(label_column)
    value_index = columns.index(value_column)
    try:
        values = [float(row[value_index] or 0) for row in result["rows"]]
    except (TypeError, ValueError):
        return [], [
            f"Diagramm nicht möglich: Die Wertespalte „{value_column}“ enthält keine "
            f"Zahlen. Verfügbare Spalten: {available}."
        ]

    # Repeated labels would be merged into one bar by the chart; number them.
    hints = []
    labels = ["–" if row[label_index] in (None, "") else str(row[label_index])
              for row in result["rows"]]
    totals = {}
    for label in labels:
        totals[label] = totals.get(label, 0) + 1
    if any(count > 1 for count in totals.values()):
        hints.append(
            f"Die Beschriftungsspalte „{label_column}“ ist nicht eindeutig. Gleiche "
            "Namen sind im Diagramm nummeriert, z. B. „Name (2)“. Für eindeutige "
            "Balken eine Spalte wählen, die je Zeile nur einmal vorkommt."
        )
        seen = {}
        for position, label in enumerate(labels):
            if totals[label] > 1:
                seen[label] = seen.get(label, 0) + 1
                if seen[label] > 1:
                    labels[position] = f"{label} ({seen[label]})"

    maximum = max(values) or 1
    bars = [
        {"label": label, "value": row[value_index] or 0,
         "width": max(0.5, value / maximum * 100)}
        for label, row, value in zip(labels, result["rows"], values)
    ]
    return bars, hints


@require_GET
def questions_page(request):
    questions = list(active_questions())
    codes = [question.code for question in questions]
    selected = request.GET.get("q") or (codes[0] if codes else "")
    reference_date, states, error = _catalog_parameters(request)
    result = None
    if not error and not codes:
        error = "Es sind keine aktiven Fragen im Katalog. Fragen in Django-Admin anlegen."
    elif not error:
        try:
            result = run_question(selected, reference_date, states)
        except QueryError as exc:
            error = str(exc)
    rows = result["rows"] if result else []
    query_string = request.GET.copy()
    query_string["q"] = selected
    # Plotly bar chart for questions with chart columns configured in admin.
    bars, chart_hints = _catalog_chart(result) if result else ([], [])
    chart_html = catalog_chart(
        [bar["label"] for bar in bars],
        [bar["value"] for bar in bars],
        _chart_unit(result["question"].chart_value),
    ) if bars else ""
    # Map of exactly the turbines this page evaluates (same rules as the view
    # v_repowering_candidates): onshore, in operation, selected states,
    # commissioned up to the 20-year cut-off.
    map_url = ""
    if result:
        source = result["source"]
        map_parameters = [("filters_present", "1")]
        map_parameters += [("state", state) for state in states]
        map_parameters += [
            ("status_filter_present", "1"),
            ("status", WindTurbine.OperationalStatus.IN_OPERATION),
            ("wind_type_filter_present", "1"),
            ("wind_type", WindTurbine.WindType.ONSHORE),
            ("bis", source["cutoff"].isoformat()),
        ]
        if source["earliest_commissioning"]:
            map_parameters.append(("von", source["earliest_commissioning"].isoformat()))
        map_url = f"{reverse('turbine-map')}?{urlencode(map_parameters)}"
    return render(request, "windenergy/questions.html", {
        "questions": questions,
        "selected_id": selected,
        "all_states": WindTurbine.DEFAULT_STATES,
        "selected_states": states,
        "reference_date": reference_date,
        "error": error,
        "result": result,
        "shown_rows": rows[:PAGE_ROW_LIMIT],
        "truncated": len(rows) > PAGE_ROW_LIMIT,
        "row_count": len(rows),
        "chart_html": chart_html,
        "chart_hints": chart_hints,
        "plotly_script": plotly_script_tag(),
        "csv_query": query_string.urlencode(),
        "map_url": map_url,
    })


@require_GET
def questions_csv(request):
    code = request.GET.get("q", "")
    reference_date, states, error = _catalog_parameters(request)
    if not error:
        try:
            result = run_question(code, reference_date, states)
        except QueryError as exc:
            error = str(exc)
    if error:
        return HttpResponse(error, status=400, content_type="text/plain; charset=utf-8")
    source = result["source"]
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="{code}_stichtag_{reference_date.isoformat()}.csv"'
    )
    response.write("\ufeff")  # BOM so Excel opens umlauts correctly
    writer = csv.writer(response, delimiter=";")
    writer.writerow([f"# {result['question'].title}"])
    writer.writerow([f"# Quelle: {source['name']}, Datenstand {source['data_stand']}"])
    writer.writerow([f"# Lizenz: {source['license']}"])
    writer.writerow([
        f"# Stichtag {reference_date:%d.%m.%Y} (Inbetriebnahme bis {source['cutoff']:%d.%m.%Y}); "
        f"Bundesländer: {', '.join(states)}"
    ])
    writer.writerow(result["columns"])
    writer.writerows(result["rows"])
    return response
