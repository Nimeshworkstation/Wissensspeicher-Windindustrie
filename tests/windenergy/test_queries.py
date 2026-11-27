"""SQL catalogue executor (windenergy/queries.py): rules, safety and source information."""

from datetime import date

from django.test import SimpleTestCase, TestCase

from windenergy.models import CatalogQuestion, WindTurbine
from windenergy.queries import (
    QueryError,
    build_parameters,
    check_select_only,
    data_stand,
    display_sql,
    render_sql,
    run_question,
    years_before,
)

from .helpers import make_turbine

STICHTAG = date(2026, 12, 31)


class HelperTests(SimpleTestCase):
    def test_years_before_handles_leap_day(self):
        self.assertEqual(years_before(date(2026, 12, 31), 20), date(2006, 12, 31))
        self.assertEqual(years_before(date(2024, 2, 29), 1), date(2023, 2, 28))

    def test_parameters(self):
        params = build_parameters(STICHTAG, ["Bremen", "Hamburg"])
        self.assertEqual(params["cutoff"], "2006-12-31")
        self.assertEqual(params["horizon"], "2011-12-31")     # cut-off + 5 years
        self.assertEqual(params["reference_date"], "2026-12-31")
        self.assertEqual((params["state_0"], params["state_1"]), ("Bremen", "Hamburg"))

    def test_only_single_select_or_with_is_allowed(self):
        self.assertEqual(check_select_only(" SELECT 1; "), "SELECT 1")
        self.assertEqual(check_select_only("with x as (select 1) select * from x"),
                         "with x as (select 1) select * from x")
        for bad in ("DELETE FROM t", "UPDATE t SET a=1", "DROP TABLE t", "SELECT 1; DELETE FROM t"):
            with self.subTest(bad):
                with self.assertRaises(QueryError):
                    check_select_only(bad)

    def test_render_inserts_filters_and_protects_percent_signs(self):
        sql = render_sql("SELECT * FROM v WHERE {base_filter} AND typ LIKE 'E-%'", ["Bremen", "Hamburg"])
        self.assertIn("state IN (%(state_0)s, %(state_1)s)", sql)
        self.assertIn("commissioning_date <= %(cutoff)s", sql)
        self.assertIn("LIKE 'E-%%'", sql)

    def test_display_sql_inserts_values_readably(self):
        sql = render_sql("SELECT 1 FROM v WHERE {base_filter}", ["O'Land"])
        shown = display_sql(sql, build_parameters(STICHTAG, ["O'Land"]))
        self.assertIn("'2006-12-31'", shown)
        self.assertIn("'O''Land'", shown)                    # quotes escaped
        self.assertNotIn("%(", shown)


class RunQuestionTests(TestCase):
    """Rules of the lead question, applied through the view v_repowering_candidates."""

    @classmethod
    def setUpTestData(cls):
        make_turbine("SEE01", commissioning_date=date(2006, 12, 31))           # on the cut-off: counts
        make_turbine("SEE02", commissioning_date=date(2007, 1, 1))             # one day too young
        make_turbine("SEE03", state="Schleswig-Holstein", gross_capacity_mw=600.0,
                     commissioning_date=date(1995, 6, 1))
        make_turbine("SEE04", wind_onshore_or_offshore=WindTurbine.WindType.OFFSHORE)
        make_turbine("SEE05", operational_status=WindTurbine.OperationalStatus.PERMANENTLY_SHUT_DOWN)
        make_turbine("SEE06", state="Bayern")                                   # not in the north
        make_turbine("SEE07", commissioning_date=None)                          # cannot be assessed
        make_turbine("SEE08", manufacturer="")                                  # unknown manufacturer

    def test_lead_question_applies_all_rules(self):
        result = run_question("Q1", STICHTAG)
        per_state = {row[0]: (row[1], row[2]) for row in result["rows"]}
        self.assertEqual(per_state, {"Niedersachsen": (2, 3.0), "Schleswig-Holstein": (1, 0.6)})
        self.assertEqual(result["source"]["candidates"], 3)
        self.assertEqual(result["source"]["missing_commissioning_date"], 1)
        self.assertEqual(result["source"]["cutoff"], date(2006, 12, 31))
        self.assertEqual(result["source"]["earliest_commissioning"], date(1995, 6, 1))

    def test_state_selection(self):
        result = run_question("Q1", STICHTAG, ["Schleswig-Holstein"])
        self.assertEqual([row[0] for row in result["rows"]], ["Schleswig-Holstein"])
        self.assertEqual(result["source"]["states"], ["Schleswig-Holstein"])

    def test_unit_list_matches_orm(self):
        listed = {row[0] for row in run_question("Q3", STICHTAG)["rows"]}
        expected = set(WindTurbine.objects.filter(
            wind_onshore_or_offshore=WindTurbine.WindType.ONSHORE,
            operational_status=WindTurbine.OperationalStatus.IN_OPERATION,
            state__in=WindTurbine.DEFAULT_STATES,
            commissioning_date__lte=date(2006, 12, 31),
        ).values_list("unit_mastr_number", flat=True))
        self.assertEqual(listed, expected)

    def test_unknown_manufacturer_is_labelled(self):
        self.assertIn("Unbekannt", [row[0] for row in run_question("Q2", STICHTAG)["rows"]])

    def test_every_seeded_question_runs_with_source(self):
        for code in CatalogQuestion.objects.values_list("code", flat=True):
            with self.subTest(code):
                result = run_question(code, STICHTAG)
                self.assertIn("Marktstammdatenregister", result["source"]["name"])
                self.assertIn("DL-DE-BY 2.0", result["source"]["license"])
                self.assertEqual(result["source"]["data_stand"], "27.11.2026")

    def test_no_states_is_an_error(self):
        with self.assertRaises(QueryError):
            run_question("Q1", STICHTAG, [])

    def test_data_stand_formats_latest_download_date(self):
        self.assertEqual(data_stand(), "27.11.2026")


class CatalogueSafetyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_turbine("SEE01")
        make_turbine("SEE02", model_designation="V47")

    def add(self, code, sql, **fields):
        return CatalogQuestion.objects.create(code=code, title=f"Testfrage {code}", sql=sql, **fields)

    def test_question_added_in_database_is_executed(self):
        self.add("Q9", "SELECT COUNT(*) AS anlagen FROM v_repowering_candidates WHERE {base_filter}")
        self.assertEqual(run_question("Q9", STICHTAG)["rows"], [(2,)])

    def test_inactive_or_unknown_question_is_refused(self):
        self.add("Q9", "SELECT 1", is_active=False)
        for code in ("Q9", "Q99"):
            with self.subTest(code):
                with self.assertRaises(QueryError):
                    run_question(code)

    def test_write_statements_never_change_data(self):
        self.add("Q8", "DELETE FROM windenergy_windturbine")
        self.add("Q9", "WITH x AS (SELECT 1) DELETE FROM windenergy_windturbine")  # passes the text check
        for code in ("Q8", "Q9"):
            with self.subTest(code):
                with self.assertRaises(QueryError):
                    run_question(code)
        self.assertEqual(WindTurbine.objects.count(), 2)
        make_turbine("SEE03")                                    # connection is writable again
        self.assertEqual(WindTurbine.objects.count(), 3)

    def test_broken_sql_raises_query_error(self):
        self.add("Q9", "SELECT no_such_column FROM v_repowering_candidates")
        with self.assertRaisesMessage(QueryError, "Q9 ist fehlerhaft"):
            run_question("Q9")

    def test_literal_percent_sign_in_stored_sql(self):
        self.add("Q9", "SELECT unit_mastr_number FROM v_repowering_candidates "
                       "WHERE {base_filter} AND model_designation LIKE 'E-%'")
        self.assertEqual(run_question("Q9", STICHTAG)["rows"], [("SEE01",)])
