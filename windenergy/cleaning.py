"""Data cleansing for MaStR wind units, run before anything is saved.

We cannot expect the source to always be clean. These steps make sure that a
bad export cannot break the database, and that every change is traceable.

Reference: the official MaStR documentation (XSD file EinheitenWind.xsd in
"Dokumentation MaStR Gesamtdatenexport"). open-mastr renames the German XSD
elements to English column names and decodes catalogue codes to text
(e.g. Bundesland 1403 -> "Niedersachsen").

Steps
-----
Before the import (whole export):
  1. Schema check      - our field list matches the XSD (field, type, required).
  2. Structure check   - all expected columns exist (checked by the import before reading).

Per row:
  3. Key check         - MaStR number present and "SEE" + 12 digits; else reject.
  4. Duplicate check   - same MaStR number seen before in this export; else reject.
  5. Completeness      - more than the MaStR number filled; else reject.

Per value:
  6. Standardise text  - Unicode NFC, remove control/invisible characters and
                         emoji, unify spaces, trim.
  7. Convert type      - number / date / date-time as defined in the XSD;
                         invalid -> empty.
  8. Allowed values    - catalogue fields must be a known value; unknown -> empty.
  9. Length            - text must fit the database column; too long -> cut.
 10. Required fields   - required per XSD but empty -> reported, row kept.

After the import:
 11. Report            - every rejection and correction is written to a CSV.

Rejected rows are not imported. Value problems never stop the import: the
value is stored empty (or cut) and the problem is reported.
"""

import math
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree

from windenergy.models import WindTurbine


# =============================================================================
# Field schema: one entry per imported column, mapped to the official XSD
# =============================================================================

@dataclass(frozen=True)
class FieldSpec:
    source: str              # column in open-mastr's table units_wind
    model_field: str         # field in WindTurbine
    kind: str                # text | code | number | date | datetime | download_date
    xsd_name: str = ""       # element in EinheitenWind.xsd ("" = added by open-mastr)
    required: bool = False   # XSD: element without minOccurs="0"
    choices: tuple = field(default_factory=tuple)  # allowed (decoded) values


FIELDS = (
    FieldSpec("unitMastrNumber", "unit_mastr_number", "text", "EinheitMastrNummer", True),
    FieldSpec("locationMastrNumber", "location_mastr_number", "text", "LokationMaStRNummer"),
    FieldSpec("state", "state", "code", "Bundesland", False, tuple(WindTurbine.State.values)),
    FieldSpec("district", "district", "text", "Landkreis"),
    FieldSpec("municipality", "municipality", "text", "Gemeinde"),
    FieldSpec("municipalityKey", "municipality_key", "text", "Gemeindeschluessel"),
    FieldSpec("postalCode", "postal_code", "text", "Postleitzahl"),
    FieldSpec("place", "place", "text", "Ort"),
    FieldSpec("latitude", "latitude", "number", "Breitengrad"),
    FieldSpec("longitude", "longitude", "number", "Laengengrad"),
    FieldSpec("registrationDate", "registration_date", "date", "Registrierungsdatum", True),
    FieldSpec("commissioningDate", "commissioning_date", "date", "Inbetriebnahmedatum"),
    FieldSpec("commissioningDateAtCurrentLocation", "commissioning_date_at_current_location",
              "date", "InbetriebnahmedatumAmAktuellenStandort"),
    FieldSpec("finalShutdownDate", "final_shutdown_date", "date", "DatumEndgueltigeStilllegung"),
    FieldSpec("unitSystemStatus", "system_status", "code", "EinheitSystemstatus", True),
    FieldSpec("unitOperationalStatus", "operational_status", "code", "EinheitBetriebsstatus",
              True, tuple(WindTurbine.OperationalStatus.values)),
    FieldSpec("energySource", "energy_source", "code", "Energietraeger", True),
    FieldSpec("grossCapacity", "gross_capacity_mw", "number", "Bruttoleistung", True),
    FieldSpec("netCapacity", "net_capacity_mw", "number", "Nettonennleistung", True),
    FieldSpec("manufacturer", "manufacturer", "code", "Hersteller"),
    FieldSpec("technology", "technology", "code", "Technologie"),
    FieldSpec("modelDesignation", "model_designation", "text", "Typenbezeichnung"),
    FieldSpec("hubHeight", "hub_height_m", "number", "Nabenhoehe"),
    FieldSpec("rotorDiameter", "rotor_diameter_m", "number", "Rotordurchmesser"),
    FieldSpec("windFarmName", "wind_farm_name", "text", "NameWindpark"),
    FieldSpec("windOnshoreOrOffshore", "wind_onshore_or_offshore", "code",
              "WindAnLandOderAufSee", True, tuple(WindTurbine.WindType.values)),
    FieldSpec("lastUpdateDate", "source_last_update", "datetime", "DatumLetzteAktualisierung", True),
    FieldSpec("downloadDate", "source_download_date", "download_date"),  # open-mastr: YYYYMMDD
)
KEY = FIELDS[0]
VALUE_FIELDS = FIELDS[1:]
SOURCE_COLUMNS = tuple(spec.source for spec in FIELDS)
MASTR_NUMBER_PATTERN = re.compile(r"SEE\d{12}")


# =============================================================================
# Results
# =============================================================================

@dataclass
class Issue:
    mastr_number: str
    field: str
    code: str        # e.g. "row_rejected", "invalid_date", "too_long"
    raw_value: str
    detail: str = ""


@dataclass
class CleanResult:
    values: dict = field(default_factory=dict)   # WindTurbine field -> clean value
    issues: list = field(default_factory=list)
    rejected: bool = False

    def report(self, mastr_number, field_name, code, raw_value, detail=""):
        raw_text = "" if raw_value is None else str(raw_value)
        self.issues.append(Issue(mastr_number, field_name, code, raw_text, detail))

    def reject(self, mastr_number, raw_value, reason):
        self.rejected = True
        self.report(mastr_number, KEY.source, "row_rejected", raw_value, reason)


def is_empty(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


# =============================================================================
# Steps 1 + 2: schema and structure (whole export)
# =============================================================================

XSD_NAMESPACE = {"xs": "http://www.w3.org/2001/XMLSchema"}
XSD_MEMBER = "Dokumentation MaStR Gesamtdatenexport/xsd/EinheitenWind.xsd"
XSD_TYPES = {  # which XSD base types each kind accepts
    "text": {"xs:string"},
    "code": {"xs:short", "xs:byte", "xs:int"},   # codes, decoded to text by open-mastr
    "number": {"xs:float", "xs:decimal", "xs:double"},
    "date": {"xs:date"},
    "datetime": {"xs:dateTime"},
}


def read_xsd_elements(xsd_bytes):
    """Return {element name: (base type, required)} for EinheitWind."""
    root = ElementTree.fromstring(xsd_bytes)
    unit = root.find(".//xs:element[@name='EinheitWind']", XSD_NAMESPACE)
    elements = {}
    for element in unit.find("xs:complexType/xs:sequence", XSD_NAMESPACE).findall(
            "xs:element", XSD_NAMESPACE):
        base = element.get("type")
        restriction = element.find("xs:simpleType/xs:restriction", XSD_NAMESPACE)
        if restriction is not None:
            base = restriction.get("base")
        elements[element.get("name")] = (base, element.get("minOccurs") != "0")
    return elements


def check_schema_against_xsd(xsd_bytes):
    """Step 1: compare FIELDS with the XSD; return a list of mismatches (empty = ok)."""
    elements = read_xsd_elements(xsd_bytes)
    mismatches = []
    for spec in FIELDS:
        if not spec.xsd_name:
            continue
        if spec.xsd_name not in elements:
            mismatches.append(f"{spec.source}: Element {spec.xsd_name} fehlt in der XSD")
            continue
        base, required = elements[spec.xsd_name]
        if base not in XSD_TYPES[spec.kind]:
            mismatches.append(f"{spec.source}: XSD-Typ {base} passt nicht zu '{spec.kind}'")
        if required != spec.required:
            mismatches.append(
                f"{spec.source}: Pflichtfeld laut XSD = {required}, im Schema = {spec.required}")
    return mismatches


def latest_docs_zip(docs_directory):
    zips = sorted(Path(docs_directory).glob("Dokumentation MaStR Gesamtdatenexport_*.zip"))
    return zips[-1] if zips else None


def check_schema_against_docs(docs_directory):
    """Step 1 on the newest downloaded documentation. Returns (zip or None, mismatches)."""
    docs_zip = latest_docs_zip(docs_directory)
    if docs_zip is None:
        return None, []
    with zipfile.ZipFile(docs_zip) as archive:
        return docs_zip, check_schema_against_xsd(archive.read(XSD_MEMBER))


# =============================================================================
# Steps 3-5: row checks
# =============================================================================

def check_key(row, result):
    """Step 3: MaStR number present and well-formed. Returns the key or None."""
    raw = row.get(KEY.source)
    key, _ = standardise_text(raw)
    if not MASTR_NUMBER_PATTERN.fullmatch(key):
        result.reject(key, raw, "MaStR-Nummer fehlt oder hat nicht das Format SEE + 12 Ziffern")
        return None
    return key


def check_duplicate(key, seen_keys, result):
    """Step 4: the same MaStR number must not appear twice in one export (first one wins)."""
    if seen_keys is None:
        return True
    if key in seen_keys:
        result.reject(key, key, "MaStR-Nummer kommt im Export mehrfach vor; erste Zeile übernommen")
        return False
    seen_keys.add(key)
    return True


def check_completeness(row, key, result):
    """Step 5: a row with nothing but the MaStR number is useless."""
    if all(is_empty(row.get(spec.source)) for spec in VALUE_FIELDS):
        result.reject(key, key, "Außer der MaStR-Nummer ist kein Feld gefüllt")
        return False
    return True


# =============================================================================
# Steps 6-10: value checks
# =============================================================================

def _is_emoji_or_symbol(character):
    code = ord(character)
    return (
        0x1F000 <= code <= 0x1FAFF      # emoji, pictographs, flags, skin tones
        or 0x2600 <= code <= 0x27BF     # miscellaneous symbols, dingbats
        or 0xFE00 <= code <= 0xFE0F     # variation selectors
        or code == 0x20E3               # combining keycap
    )


def standardise_text(value):
    """Step 6: return (clean text, list of changes).

    Umlauts and normal punctuation are kept.
    """
    if value is None:
        return "", []
    text = unicodedata.normalize("NFC", str(value))
    removed = False
    kept = []
    for character in text:
        if character in "\t\n\r":
            kept.append(character)                   # whitespace, unified below
        elif unicodedata.category(character) in ("Cc", "Cf", "Cs", "Co", "Cn") \
                or _is_emoji_or_symbol(character):
            removed = True                           # control, invisible, emoji
        else:
            kept.append(character)
    without_removed = "".join(kept)
    # \s also matches no-break spaces (U+00A0, U+2007, U+202F) in Python.
    cleaned = re.sub(r"\s+", " ", without_removed).strip()
    changes = []
    if removed:
        changes.append("removed_characters")
    if cleaned != without_removed:
        changes.append("whitespace_normalized")
    return cleaned, changes


# Backwards-compatible name used elsewhere.
clean_text = standardise_text


def parse_number(value):
    """Finite float, None when empty; raises ValueError otherwise."""
    if is_empty(value):
        return None
    number = float(value.strip()) if isinstance(value, str) else float(value)
    if not math.isfinite(number):
        raise ValueError("not a finite number")
    return number


def parse_date(value):
    """ISO date (YYYY-MM-DD, a time part is ignored); raises ValueError otherwise."""
    if is_empty(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T].*)?", text):
        raise ValueError("not an ISO date")
    return date.fromisoformat(text[:10])


def parse_datetime_text(value):
    """ISO date-time, kept as text; raises ValueError otherwise."""
    if is_empty(value):
        return ""
    text = str(value).strip()
    datetime.fromisoformat(text.replace("Z", "+00:00"))
    return text


def parse_download_date(value):
    """open-mastr download date YYYYMMDD, kept as text; raises ValueError otherwise."""
    if is_empty(value):
        return ""
    text = str(value).strip()
    datetime.strptime(text, "%Y%m%d")
    return text


CONVERTERS = {
    "number": (parse_number, "invalid_number"),
    "date": (parse_date, "invalid_date"),
    "datetime": (parse_datetime_text, "invalid_datetime"),
    "download_date": (parse_download_date, "invalid_value"),
}


def convert_type(spec, raw, key, result):
    """Step 7: convert to the type defined in the XSD; invalid -> empty."""
    if spec.kind in ("text", "code"):
        value, changes = standardise_text(raw)                # step 6
        for change in changes:
            result.report(key, spec.source, change, raw)
        return value
    converter, problem = CONVERTERS[spec.kind]
    try:
        return converter(raw)
    except (TypeError, ValueError):
        result.report(key, spec.source, problem, raw)
        return None if spec.kind in ("number", "date") else ""


def check_allowed_values(spec, value, raw, key, result):
    """Step 8: catalogue fields must contain a known value; unknown -> empty."""
    if spec.choices and value and value not in spec.choices:
        result.report(key, spec.source, "unknown_value", raw, "nicht in der erlaubten Werteliste")
        return ""
    return value


def check_length(spec, value, raw, key, result):
    """Step 9: text must fit the database column; too long -> cut and reported."""
    limit = WindTurbine._meta.get_field(spec.model_field).max_length
    if isinstance(value, str) and limit and len(value) > limit:
        result.report(key, spec.source, "too_long", raw, f"{len(value)} > {limit} Zeichen, gekürzt")
        return value[:limit]
    return value


def check_required(spec, value, raw, key, result):
    """Step 10: required per XSD but empty -> reported (the row is kept)."""
    if spec.required and value in (None, ""):
        result.report(key, spec.source, "missing_required", raw,
                      f"Pflichtfeld laut XSD ({spec.xsd_name})")


# =============================================================================
# One row, all steps in order
# =============================================================================

def clean_row(row, seen_keys=None):
    """Run steps 3-10 on one source row (open-mastr column -> value).

    seen_keys: a set shared across the whole export for the duplicate check.
    """
    result = CleanResult()

    key = check_key(row, result)                                   # step 3
    if key is None:
        return result
    if not check_duplicate(key, seen_keys, result):                # step 4
        return result
    if not check_completeness(row, key, result):                   # step 5
        return result

    result.values[KEY.model_field] = key
    for spec in VALUE_FIELDS:
        raw = row.get(spec.source)
        value = convert_type(spec, raw, key, result)               # steps 6 + 7
        value = check_allowed_values(spec, value, raw, key, result)  # step 8
        value = check_length(spec, value, raw, key, result)          # step 9
        check_required(spec, value, raw, key, result)                # step 10
        result.values[spec.model_field] = value
    return result
