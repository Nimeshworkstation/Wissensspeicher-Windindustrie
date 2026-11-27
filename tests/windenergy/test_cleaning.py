"""Data cleansing (windenergy/cleaning.py): every step on its own, then clean_row as a whole."""

import unittest
import zipfile
from datetime import date

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from windenergy import cleaning
from windenergy.cleaning import (
    FIELDS,
    check_schema_against_docs,
    check_schema_against_xsd,
    clean_row,
    parse_date,
    parse_datetime_text,
    parse_download_date,
    parse_number,
    standardise_text,
)

from .helpers import key_only_row, source_row


def codes(result):
    return {(issue.field, issue.code) for issue in result.issues}


class StandardiseTextTests(SimpleTestCase):
    """Step 6."""

    def test_trims_and_collapses_whitespace(self):
        self.assertEqual(standardise_text("  Windpark  Saterland "),
                         ("Windpark Saterland", ["whitespace_normalized"]))

    def test_line_breaks_and_no_break_spaces_become_spaces(self):
        self.assertEqual(standardise_text("Zeile1\nZeile2")[0], "Zeile1 Zeile2")
        self.assertEqual(standardise_text("Nord Tank")[0], "Nord Tank")

    def test_removes_emoji_control_and_invisible_characters(self):
        self.assertEqual(standardise_text("E-66\U0001F32C️"), ("E-66", ["removed_characters"]))
        self.assertEqual(standardise_text("A​B\x07")[0], "AB")

    def test_keeps_umlauts_and_punctuation(self):
        self.assertEqual(standardise_text("Fuhrländer GmbH & Co. KG"), ("Fuhrländer GmbH & Co. KG", []))

    def test_unicode_is_normalised(self):
        decomposed = "Fuhrländer"          # a + combining diaeresis
        self.assertEqual(standardise_text(decomposed)[0], "Fuhrländer")

    def test_none_becomes_empty(self):
        self.assertEqual(standardise_text(None), ("", []))


class TypeConversionTests(SimpleTestCase):
    """Step 7."""

    def test_numbers(self):
        self.assertEqual(parse_number(" 1500.5 "), 1500.5)
        self.assertEqual(parse_number(2), 2.0)
        self.assertIsNone(parse_number(""))
        self.assertIsNone(parse_number(None))
        for bad in ("abc", "nan", "inf"):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    parse_number(bad)

    def test_dates(self):
        self.assertEqual(parse_date("2006-12-31"), date(2006, 12, 31))
        self.assertEqual(parse_date("2006-12-31 00:00:00"), date(2006, 12, 31))
        self.assertIsNone(parse_date(""))
        for bad in ("31.12.2006", "2006-13-01", "gestern"):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    parse_date(bad)

    def test_datetimes_are_validated_and_kept_as_text(self):
        self.assertEqual(parse_datetime_text("2026-11-20 10:00:00.123"), "2026-11-20 10:00:00.123")
        self.assertEqual(parse_datetime_text(None), "")
        with self.assertRaises(ValueError):
            parse_datetime_text("gestern")

    def test_download_date_format(self):
        self.assertEqual(parse_download_date("20261127"), "20261127")
        with self.assertRaises(ValueError):
            parse_download_date("2026-11-27")


class CleanRowTests(TestCase):
    """Steps 3-10 through clean_row()."""

    def test_valid_row_passes_unchanged(self):
        result = clean_row(source_row())
        self.assertFalse(result.rejected)
        self.assertEqual(result.issues, [])
        self.assertEqual(result.values["unit_mastr_number"], "SEE123456789012")
        self.assertEqual(result.values["commissioning_date"], date(2001, 5, 1))
        self.assertEqual(result.values["gross_capacity_mw"], 1500.0)
        self.assertEqual(set(result.values), {spec.model_field for spec in FIELDS})

    def test_step3_rejects_missing_or_malformed_key(self):
        for key in (None, "", "SEE12", "XYZ123456789012", "see123456789012"):
            with self.subTest(key):
                result = clean_row(source_row(unitMastrNumber=key))
                self.assertTrue(result.rejected)
                self.assertIn(("unitMastrNumber", "row_rejected"), codes(result))

    def test_step3_trims_key_before_checking(self):
        self.assertFalse(clean_row(source_row(unitMastrNumber=" SEE123456789012 ")).rejected)

    def test_step4_rejects_duplicates_keeps_first(self):
        seen = set()
        self.assertFalse(clean_row(source_row(), seen).rejected)
        second = clean_row(source_row(windFarmName="Zweite"), seen)
        self.assertTrue(second.rejected)
        self.assertIn("mehrfach", second.issues[0].detail)

    def test_step5_rejects_row_with_only_the_key(self):
        result = clean_row(key_only_row("SEE123456789012"))
        self.assertTrue(result.rejected)
        self.assertIn("kein Feld", result.issues[0].detail)

    def test_step7_invalid_values_become_empty_and_are_reported(self):
        result = clean_row(source_row(commissioningDate="31.12.2006", hubHeight="hoch",
                                      lastUpdateDate="gestern", downloadDate="27.11.2026"))
        self.assertFalse(result.rejected)
        self.assertIsNone(result.values["commissioning_date"])
        self.assertIsNone(result.values["hub_height_m"])
        self.assertEqual(result.values["source_last_update"], "")
        self.assertEqual(result.values["source_download_date"], "")
        self.assertTrue({("commissioningDate", "invalid_date"), ("hubHeight", "invalid_number"),
                         ("lastUpdateDate", "invalid_datetime"), ("downloadDate", "invalid_value")}
                        <= codes(result))

    def test_step8_unknown_catalogue_values_become_empty(self):
        result = clean_row(source_row(state="Atlantis", unitOperationalStatus="Kaputt",
                                      windOnshoreOrOffshore="Im Weltall"))
        self.assertEqual(result.values["state"], "")
        self.assertEqual(result.values["operational_status"], "")
        self.assertEqual(result.values["wind_onshore_or_offshore"], "")
        self.assertIn(("state", "unknown_value"), codes(result))

    def test_step8_catalogue_fields_without_list_are_free_text(self):
        result = clean_row(source_row(manufacturer="Neuer Hersteller AG"))
        self.assertEqual(result.values["manufacturer"], "Neuer Hersteller AG")
        self.assertEqual(result.issues, [])

    def test_step9_too_long_text_is_cut_and_reported(self):
        result = clean_row(source_row(windFarmName="W" * 250))
        self.assertEqual(len(result.values["wind_farm_name"]), 200)
        self.assertIn(("windFarmName", "too_long"), codes(result))

    def test_step10_missing_required_field_is_reported_row_kept(self):
        result = clean_row(source_row(grossCapacity=None, registrationDate=""))
        self.assertFalse(result.rejected)
        self.assertTrue({("grossCapacity", "missing_required"),
                         ("registrationDate", "missing_required")} <= codes(result))

    def test_optional_empty_fields_are_not_reported(self):
        result = clean_row(source_row(hubHeight=None, windFarmName=None, finalShutdownDate=None))
        self.assertEqual(result.issues, [])

    def test_issue_keeps_raw_value_for_traceability(self):
        result = clean_row(source_row(windFarmName="  Windpark  Nord "))
        issue = next(i for i in result.issues if i.field == "windFarmName")
        self.assertEqual(issue.raw_value, "  Windpark  Nord ")
        self.assertEqual(issue.mastr_number, "SEE123456789012")


XSD_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="EinheitenWind"><xs:complexType><xs:sequence>
    <xs:element name="EinheitWind" maxOccurs="unbounded"><xs:complexType><xs:sequence>
      {elements}
    </xs:sequence></xs:complexType></xs:element>
  </xs:sequence></xs:complexType></xs:element>
</xs:schema>"""

XSD_TYPE_FOR_KIND = {"text": "xs:string", "code": "xs:short", "number": "xs:float",
                     "date": "xs:date", "datetime": "xs:dateTime"}


def make_xsd(overrides=None, drop=()):
    """An XSD that matches FIELDS, optionally with changed types/required flags."""
    overrides = overrides or {}
    parts = []
    for spec in FIELDS:
        if not spec.xsd_name or spec.xsd_name in drop:
            continue
        xsd_type, required = overrides.get(spec.xsd_name, (XSD_TYPE_FOR_KIND[spec.kind], spec.required))
        optional = "" if required else ' minOccurs="0"'
        parts.append(f'<xs:element type="{xsd_type}" name="{spec.xsd_name}"{optional}/>')
    return XSD_TEMPLATE.format(elements="\n".join(parts)).encode("utf-8")


class SchemaCheckTests(SimpleTestCase):
    """Step 1."""

    def test_matching_xsd_has_no_mismatches(self):
        self.assertEqual(check_schema_against_xsd(make_xsd()), [])

    def test_changed_type_is_detected(self):
        mismatches = check_schema_against_xsd(make_xsd({"Inbetriebnahmedatum": ("xs:string", False)}))
        self.assertEqual(len(mismatches), 1)
        self.assertIn("commissioningDate", mismatches[0])

    def test_changed_required_flag_is_detected(self):
        mismatches = check_schema_against_xsd(make_xsd({"Nabenhoehe": ("xs:float", True)}))
        self.assertIn("Pflichtfeld", mismatches[0])

    def test_missing_element_is_detected(self):
        mismatches = check_schema_against_xsd(make_xsd(drop={"Bruttoleistung"}))
        self.assertIn("fehlt", mismatches[0])

    def test_docs_zip_is_read(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "Dokumentation MaStR Gesamtdatenexport_20261127.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr(cleaning.XSD_MEMBER, make_xsd())
            found, mismatches = check_schema_against_docs(tmp)
            self.assertEqual(found.name, archive.name)
            self.assertEqual(mismatches, [])

    def test_no_docs_zip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(check_schema_against_docs(tmp), (None, []))

    def test_schema_matches_the_real_downloaded_documentation(self):
        docs = settings.BASE_DIR / "data" / "data" / "docs_download"
        found, mismatches = check_schema_against_docs(docs)
        if found is None:
            raise unittest.SkipTest("No MaStR documentation zip downloaded.")
        self.assertEqual(mismatches, [])
