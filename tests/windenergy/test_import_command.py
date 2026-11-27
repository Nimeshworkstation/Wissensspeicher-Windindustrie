"""MaStR import (manage.py import_wind_data): cleaning, rejection, reporting and safety.

Every test builds a small temporary open-mastr database; the real data is never touched.
"""

import csv
import io
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import TestCase

from windenergy import cleaning
from windenergy.models import WindTurbine

from .helpers import key_only_row, make_source_db, make_turbine, source_row


class ImportCommandTests(TestCase):
    def run_import(self, rows, **options):
        """Import rows from a temporary source; return (stdout, issue CSV rows, temp dir path)."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        source = make_source_db(self.tmp.name, rows)
        out = io.StringIO()
        with self.settings(BASE_DIR=Path(self.tmp.name)):
            call_command("import_wind_data", source=source, stdout=out, **options)
        issue_files = list((Path(self.tmp.name) / "logs" / "importing").glob("*-issues.csv"))
        issues = []
        if issue_files:
            with open(issue_files[0], encoding="utf-8-sig", newline="") as handle:
                issues = list(csv.DictReader(handle, delimiter=";"))
        return out.getvalue(), issues

    def test_valid_rows_are_imported_with_clean_values(self):
        output, issues = self.run_import([
            source_row(),
            source_row(unitMastrNumber="SEE000000000002", windFarmName=" Windpark  Nord \U0001F32C"),
        ])
        self.assertEqual(WindTurbine.objects.count(), 2)
        self.assertEqual(WindTurbine.objects.get(unit_mastr_number="SEE000000000002").wind_farm_name,
                         "Windpark Nord")
        self.assertIn("Imported or updated 2 wind units", output)
        self.assertIn("Rejected rows: 0", output)
        self.assertEqual({row["problem"] for row in issues},
                         {"whitespace_normalized", "removed_characters"})

    def test_rejected_rows_are_not_imported_and_reported(self):
        output, issues = self.run_import([
            source_row(),
            key_only_row("SEE000000000003"),
            source_row(unitMastrNumber="kaputt"),
        ])
        self.assertEqual(list(WindTurbine.objects.values_list("unit_mastr_number", flat=True)),
                         ["SEE123456789012"])
        self.assertIn("Rejected rows: 2", output)
        rejected = [row for row in issues if row["problem"] == "row_rejected"]
        self.assertEqual(len(rejected), 2)

    def test_duplicate_mastr_number_keeps_first_row(self):
        output, _ = self.run_import([source_row(windFarmName="Erste"), source_row(windFarmName="Zweite")])
        self.assertEqual(WindTurbine.objects.get().wind_farm_name, "Erste")
        self.assertIn("Rejected rows: 1", output)

    def test_existing_units_are_updated_not_duplicated(self):
        make_turbine("SEE123456789012", wind_farm_name="Alt")
        self.run_import([source_row(windFarmName="Neu")])
        self.assertEqual(WindTurbine.objects.count(), 1)
        self.assertEqual(WindTurbine.objects.get().wind_farm_name, "Neu")

    def test_no_issue_file_when_data_is_clean(self):
        output, issues = self.run_import([source_row()])
        self.assertEqual(issues, [])
        self.assertIn("Cleaning issues: 0.", output)

    def test_failed_batch_rolls_back_the_whole_import(self):
        make_turbine("SEE999999999999", wind_farm_name="Alter Stand")
        rows = [source_row(), source_row(unitMastrNumber="SEE000000000002"),
                source_row(unitMastrNumber="SEE999999999999", windFarmName="Neuer Stand")]
        real_bulk_create = WindTurbine.objects.bulk_create
        calls = {"n": 0}

        def fail_on_second_batch(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise DatabaseError("simulated failure")
            return real_bulk_create(*args, **kwargs)

        with mock.patch.object(WindTurbine.objects, "bulk_create", side_effect=fail_on_second_batch):
            with self.assertRaises(CommandError) as raised:
                self.run_import(rows, batch_size=1)
        self.assertIn("rolled back", str(raised.exception))
        self.assertFalse(WindTurbine.objects.filter(unit_mastr_number="SEE123456789012").exists())
        self.assertEqual(WindTurbine.objects.get().wind_farm_name, "Alter Stand")

    def test_missing_column_stops_before_writing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        columns = tuple(c for c in cleaning.SOURCE_COLUMNS if c != "hubHeight")
        source = make_source_db(tmp.name, [source_row()], columns=columns)
        with self.settings(BASE_DIR=Path(tmp.name)):
            with self.assertRaises(CommandError) as raised:
                call_command("import_wind_data", source=source, stdout=io.StringIO())
        self.assertIn("missing column(s): hubHeight", str(raised.exception))
        self.assertEqual(WindTurbine.objects.count(), 0)

    def test_missing_table_stops_before_writing(self):
        import sqlite3
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        source = Path(tmp.name) / "empty.db"
        sqlite3.connect(source).close()
        with self.settings(BASE_DIR=Path(tmp.name)), self.assertRaises(CommandError) as raised:
            call_command("import_wind_data", source=source, stdout=io.StringIO())
        self.assertIn("the whole table", str(raised.exception))

    def test_missing_source_file(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with self.settings(BASE_DIR=Path(tmp.name)), self.assertRaises(CommandError):
            call_command("import_wind_data", source=Path(tmp.name) / "missing.db", stdout=io.StringIO())

    def test_invalid_batch_size(self):
        with self.assertRaises(CommandError):
            self.run_import([source_row()], batch_size=0)

    def test_schema_mismatch_is_reported_but_import_continues(self):
        from tests.windenergy.test_cleaning import make_xsd
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        source = make_source_db(tmp.name, [source_row()])
        docs = Path(tmp.name) / "docs_download"         # next to sqlite/, like open-mastr's layout
        docs.mkdir()
        with zipfile.ZipFile(docs / "Dokumentation MaStR Gesamtdatenexport_20261127.zip", "w") as archive:
            archive.writestr(cleaning.XSD_MEMBER, make_xsd({"Nabenhoehe": ("xs:string", False)}))
        out = io.StringIO()
        with self.settings(BASE_DIR=Path(tmp.name)):
            call_command("import_wind_data", source=source, stdout=out)
        self.assertIn("1 difference(s) between cleaning schema", out.getvalue())
        self.assertEqual(WindTurbine.objects.count(), 1)
