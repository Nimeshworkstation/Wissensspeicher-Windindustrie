"""Backend logic behind the pages: calculations, filters, endpoints and helpers.

Only computed values, status codes and headers are checked here, never page layout.
"""

import csv
import io
import re
from datetime import date
from unittest import mock

from django.test import RequestFactory, TestCase
from django.urls import reverse

from windenergy import views
from windenergy.models import CatalogQuestion, QuerySuggestion, WindTurbine

from .helpers import NORTH, make_turbine

ALL_STATUSES = list(WindTurbine.OperationalStatus.values)
BOTH_TYPES = list(WindTurbine.WindType.values)


def context_for(params=None):
    request = RequestFactory().get("/", params or {})
    return views.dashboard_context(request)


class DashboardCalculationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_turbine("SEE01", commissioning_date=date(2000, 3, 1), gross_capacity_mw=1500.0)
        make_turbine("SEE02", commissioning_date=date(2000, 9, 1), gross_capacity_mw=2000.0,
                     manufacturer="Vestas Deutschland GmbH")
        make_turbine("SEE03", commissioning_date=date(2002, 1, 1), manufacturer="")
        make_turbine("SEE04", commissioning_date=date(2002, 6, 1), state="Bayern")
        make_turbine("SEE05", commissioning_date=date(2010, 1, 1),
                     wind_onshore_or_offshore=WindTurbine.WindType.OFFSHORE)
        make_turbine("SEE06", commissioning_date=date(2001, 1, 1),
                     operational_status=WindTurbine.OperationalStatus.PERMANENTLY_SHUT_DOWN)
        make_turbine("SEE07", commissioning_date=None,
                     operational_status=WindTurbine.OperationalStatus.PLANNED)

    def test_default_range_is_whole_data_range(self):
        context, error = context_for()
        self.assertEqual(error, "")
        self.assertEqual((context["von_iso"], context["bis_iso"]), ("2000-03-01", "2010-01-01"))

    def test_default_filters_north_in_operation_onshore(self):
        context, _ = context_for()
        self.assertEqual(context["results"]["count"], "3")           # SEE01, SEE02, SEE03
        self.assertEqual(context["results"]["capacity"], "5,00")     # 1.5 + 2.0 + 1.5 MW

    def test_manufacturer_summary_labels_unknown(self):
        context, _ = context_for()
        names = {item["name"]: item["count"] for item in context["results"]["manufacturers"]}
        self.assertEqual(names, {"ENERCON GmbH": 1, "Vestas Deutschland GmbH": 1, "Unbekannt": 1})

    def test_date_range_filters_commissioning_date(self):
        context, _ = context_for({"von": "2000-06-01", "bis": "2002-12-31"})
        self.assertEqual(context["results"]["count"], "2")           # SEE02, SEE03

    def test_von_after_bis_is_an_error(self):
        _, error = context_for({"von": "2005-01-01", "bis": "2000-01-01"})
        self.assertIn("Von darf nicht nach Bis", error)

    def test_invalid_date_is_an_error(self):
        _, error = context_for({"von": "31.12.2006"})
        self.assertTrue(error)

    def test_state_status_and_wind_type_filters(self):
        context, _ = context_for({
            "filters_present": "1", "state": NORTH + ["Bayern"],
            "status_filter_present": "1", "status": ALL_STATUSES,
            "wind_type_filter_present": "1", "wind_type": BOTH_TYPES,
        })
        self.assertEqual(context["results"]["count"], "6")           # all dated units
        cards = {card["label"]: card["count"] for card in context["comparison_cards"]}
        self.assertEqual(cards, {"Onshore": 5, "Offshore": 1})

    def test_unknown_filter_values_are_ignored(self):
        context, _ = context_for({"filters_present": "1", "state": ["Atlantis"]})
        self.assertEqual(context["selected_states"], [])
        self.assertEqual(context["results"]["count"], "0")

    def test_status_cards_compare_all_statuses(self):
        context, _ = context_for({"status_filter_present": "1", "status": ["In Betrieb"]})
        counts = {card["label"]: card["count"] for card in context["status_cards"]}
        self.assertEqual(counts["In Betrieb"], 3)
        self.assertEqual(counts["Endgültig stillgelegt"], 1)          # shown although not selected

    def test_missing_commissioning_date_is_counted(self):
        context, _ = context_for()
        self.assertEqual(context["missing_commissioning_count"], "1")

    def test_commissioning_per_year_fills_empty_years(self):
        context, _ = context_for({"von": "2000-01-01", "bis": "2002-12-31"})
        chart = context["commissioning_chart"]
        self.assertIn('"x":[2000,2001,2002]', chart)
        self.assertIn('"y":[2,0,1]', chart)


class TurbineMapEndpointTests(TestCase):
    def setUp(self):
        make_turbine("SEE01", latitude=53.0, longitude=8.0)

    def test_map_may_only_be_framed_by_own_site(self):
        with self.settings(CARTO_BASEMAP_API_KEY="test-key"):
            response = self.client.get(reverse("turbine-map"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(self.client.get(reverse("dashboard"))["X-Frame-Options"], "DENY")

    def test_missing_basemap_key_returns_503(self):
        with self.settings(CARTO_BASEMAP_API_KEY=""):
            self.assertEqual(self.client.get(reverse("turbine-map")).status_code, 503)

    def test_invalid_range_returns_400(self):
        with self.settings(CARTO_BASEMAP_API_KEY="test-key"):
            response = self.client.get(reverse("turbine-map"), {"von": "2010-01-01", "bis": "2000-01-01"})
        self.assertEqual(response.status_code, 400)


class CatalogueEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_turbine("SEE01", commissioning_date=date(2000, 1, 1))
        make_turbine("SEE02", commissioning_date=date(2001, 1, 1), state="Bremen")

    def test_parameters_are_fixed_to_the_lead_question(self):
        request = RequestFactory().get("/", {"states_present": "1", "stichtag": "2030-01-01",
                                             "state": ["Bremen", "Bayern"]})
        reference_date, states, error = views._catalog_parameters(request)
        self.assertEqual(reference_date, date(2026, 12, 31))        # date cannot be changed
        self.assertEqual(states, ["Bremen"])                         # only northern states
        self.assertEqual(error, "")

    def test_no_state_is_an_error(self):
        request = RequestFactory().get("/", {"states_present": "1"})
        self.assertTrue(views._catalog_parameters(request)[2])

    def test_csv_export_contains_source_and_all_rows(self):
        response = self.client.get(reverse("questions-csv"), {"q": "Q3"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Q3_stichtag_2026-12-31.csv", response["Content-Disposition"])
        lines = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
        self.assertTrue(lines[1][0].startswith("# Quelle: Bundesnetzagentur"))
        self.assertIn("DL-DE-BY 2.0", lines[2][0])
        self.assertEqual(lines[4][0], "mastr_nr")                    # header row
        self.assertEqual({row[0] for row in lines[5:]}, {"SEE01", "SEE02"})

    def test_csv_with_invalid_question_returns_400(self):
        self.assertEqual(self.client.get(reverse("questions-csv"), {"q": "Q99"}).status_code, 400)

    def test_map_url_matches_page_rules(self):
        response = self.client.get(reverse("questions"), {"q": "Q1"})
        url = response.context["map_url"]
        for part in ("status=In+Betrieb", "wind_type=Windenergie+an+Land", "bis=2006-12-31"):
            self.assertIn(part, url)


class CatalogueChartHelperTests(TestCase):
    def result(self, columns, rows, label="", value=""):
        question = CatalogQuestion(code="Q9", title="T", sql="", chart_label=label, chart_value=value)
        return {"question": question, "columns": columns, "rows": rows}

    def test_unit_comes_from_column_name(self):
        self.assertEqual(views._chart_unit("leistung_mw"), "MW")
        self.assertEqual(views._chart_unit("anteil_prozent"), "%")
        self.assertEqual(views._chart_unit("nabenhoehe_m"), "m")
        self.assertEqual(views._chart_unit("anlagen"), "")

    def test_no_chart_configured_gives_no_hint(self):
        self.assertEqual(views._catalog_chart(self.result(["a"], [(1,)])), ([], []))

    def test_wrong_column_gives_hint_with_available_columns(self):
        bars, hints = views._catalog_chart(self.result(["typ", "anlagen"], [("E-66", 3)], "typ", "anlage"))
        self.assertEqual(bars, [])
        self.assertIn("„anlage“ ist nicht im Ergebnis", hints[0])
        self.assertIn("typ, anlagen", hints[0])

    def test_text_value_column_gives_hint(self):
        _, hints = views._catalog_chart(self.result(["typ", "name"], [("E-66", "x")], "typ", "name"))
        self.assertIn("keine Zahlen", hints[0])

    def test_duplicate_labels_are_numbered(self):
        bars, hints = views._catalog_chart(
            self.result(["hersteller", "anlagen"], [("ENERCON", 3), ("Vestas", 2), ("ENERCON", 1)],
                        "hersteller", "anlagen"))
        self.assertEqual([bar["label"] for bar in bars], ["ENERCON", "Vestas", "ENERCON (2)"])
        self.assertIn("nicht eindeutig", hints[0])


class QuerySuggestionEndpointTests(TestCase):
    def test_valid_suggestion_is_saved(self):
        response = self.client.post(reverse("query-suggestion"),
                                    {"question": "Wie viele Anlagen laufen 2028 aus?", "details": "Nur SH"})
        self.assertEqual(response.status_code, 302)
        suggestion = QuerySuggestion.objects.get()
        self.assertEqual((suggestion.question, suggestion.details, suggestion.status),
                         ("Wie viele Anlagen laufen 2028 aus?", "Nur SH", "new"))

    def test_empty_question_is_not_saved(self):
        response = self.client.post(reverse("query-suggestion"), {"question": "", "details": "x"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(QuerySuggestion.objects.exists())


class ChatEndpointTests(TestCase):
    def test_empty_message_returns_204(self):
        self.assertEqual(self.client.post(reverse("chat"), {"message": "  "}).status_code, 204)

    def test_answer_and_sources_from_service(self):
        reply = {"answer": "Antwort [1]", "sources": [{"citation": 1, "title": "Doku", "page": None}]}
        with mock.patch.object(views, "get_chatbot_reply", return_value=reply) as service:
            response = self.client.post(reverse("chat"), {"message": "Frage?"})
        service.assert_called_once_with("Frage?")
        self.assertEqual(response.context["bot_reply"], "Antwort [1]")
        self.assertEqual(response.context["bot_sources"], reply["sources"])

    def test_service_failure_gives_fallback_answer(self):
        with mock.patch.object(views, "get_chatbot_reply", side_effect=RuntimeError("down")):
            response = self.client.post(reverse("chat"), {"message": "Frage?"})
        self.assertIn("nicht verfügbar", response.context["bot_reply"])
        self.assertEqual(response.context["bot_sources"], [])

    def test_long_message_is_truncated(self):
        with mock.patch.object(views, "get_chatbot_reply", return_value={"answer": "", "sources": []}) as service:
            self.client.post(reverse("chat"), {"message": "x" * 800})
        self.assertEqual(len(service.call_args.args[0]), 500)
