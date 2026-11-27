"""Models, seeded data and the database view created by migrations."""

from datetime import date

from django.db import connection
from django.test import TestCase

from windenergy.models import CatalogQuestion, QuerySuggestion, WindTurbine

from .helpers import make_turbine


class WindTurbineModelTests(TestCase):
    def test_wind_type_values_are_mastr_text_labels_are_short(self):
        self.assertEqual(WindTurbine.WindType.ONSHORE.value, "Windenergie an Land")
        self.assertEqual(WindTurbine.WindType.ONSHORE.label, "Onshore")
        self.assertEqual(WindTurbine.WindType.OFFSHORE.label, "Offshore")

    def test_defaults_describe_the_lead_question(self):
        self.assertEqual(WindTurbine.MIN_REPOWERING_AGE_YEARS, 20)
        self.assertEqual(set(WindTurbine.DEFAULT_STATES),
                         {"Schleswig-Holstein", "Hamburg", "Bremen", "Niedersachsen",
                          "Mecklenburg-Vorpommern"})

    def test_mastr_number_is_primary_key(self):
        make_turbine("SEE01")
        self.assertEqual(WindTurbine.objects.get(pk="SEE01").unit_mastr_number, "SEE01")


class CandidateViewTests(TestCase):
    """The view v_repowering_candidates holds the shared rule: onshore, in operation, dated."""

    def test_view_filters_onshore_in_operation_with_date(self):
        make_turbine("SEE01")
        make_turbine("SEE02", wind_onshore_or_offshore=WindTurbine.WindType.OFFSHORE)
        make_turbine("SEE03", operational_status=WindTurbine.OperationalStatus.PLANNED)
        make_turbine("SEE04", commissioning_date=None)
        with connection.cursor() as cursor:
            cursor.execute("SELECT unit_mastr_number FROM v_repowering_candidates")
            self.assertEqual([row[0] for row in cursor.fetchall()], ["SEE01"])


class CatalogQuestionTests(TestCase):
    def test_starter_questions_are_seeded_by_migration(self):
        self.assertEqual(list(CatalogQuestion.objects.values_list("code", flat=True)),
                         ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"])

    def test_note_list_splits_lines_and_drops_empty_ones(self):
        question = CatalogQuestion(code="Q9", title="T", sql="SELECT 1",
                                   notes="Erster Hinweis\n\n  Zweiter Hinweis  \n")
        self.assertEqual(question.note_list, ["Erster Hinweis", "Zweiter Hinweis"])
        self.assertEqual(str(question), "Q9 – T")


class QuerySuggestionTests(TestCase):
    def test_new_suggestion_defaults(self):
        suggestion = QuerySuggestion.objects.create(question="Wie viele Anlagen laufen 2028 aus?")
        self.assertEqual(suggestion.status, QuerySuggestion.Status.NEW)
        self.assertIsNotNone(suggestion.submitted_at)
        self.assertEqual(str(suggestion), "Wie viele Anlagen laufen 2028 aus?")
