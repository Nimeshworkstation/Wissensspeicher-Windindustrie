"""Shared test data for the windenergy backend tests."""

import sqlite3
from datetime import date
from pathlib import Path

from django.utils import timezone

from windenergy.cleaning import FIELDS, SOURCE_COLUMNS
from windenergy.models import WindTurbine

NORTH = ["Schleswig-Holstein", "Hamburg", "Bremen", "Niedersachsen", "Mecklenburg-Vorpommern"]


def make_turbine(number, **fields):
    """Create one WindTurbine with sensible defaults (onshore, in operation, Niedersachsen)."""
    values = {
        "state": "Niedersachsen",
        "operational_status": WindTurbine.OperationalStatus.IN_OPERATION,
        "wind_onshore_or_offshore": WindTurbine.WindType.ONSHORE,
        "commissioning_date": date(2000, 1, 1),
        "gross_capacity_mw": 1500.0,  # the field holds kW
        "manufacturer": "ENERCON GmbH",
        "model_designation": "E-66",
        "source_download_date": "20261127",
        "imported_at": timezone.now(),
    }
    values.update(fields)
    return WindTurbine.objects.create(unit_mastr_number=number, **values)


def source_row(**overrides):
    """One valid row as open-mastr delivers it (English column names, decoded codes)."""
    row = {
        "unitMastrNumber": "SEE123456789012", "locationMastrNumber": "SEL123456789012",
        "state": "Niedersachsen", "district": "Aurich", "municipality": "Aurich",
        "municipalityKey": "03452001", "postalCode": "26603", "place": "Aurich",
        "latitude": 53.4, "longitude": 7.4, "registrationDate": "2019-02-01",
        "commissioningDate": "2001-05-01", "commissioningDateAtCurrentLocation": None,
        "finalShutdownDate": None, "unitSystemStatus": "Aktiviert",
        "unitOperationalStatus": "In Betrieb", "energySource": "Wind",
        "grossCapacity": 1500.0, "netCapacity": 1500.0, "manufacturer": "ENERCON GmbH",
        "technology": "Horizontalläufer", "modelDesignation": "E-66", "hubHeight": 67.0,
        "rotorDiameter": 66.0, "windFarmName": "Windpark Test",
        "windOnshoreOrOffshore": "Windenergie an Land",
        "lastUpdateDate": "2026-11-20 10:00:00.123", "downloadDate": "20261127",
    }
    row.update(overrides)
    return row


def key_only_row(number):
    """A row where nothing but the MaStR number is filled."""
    return {spec.source: None for spec in FIELDS} | {"unitMastrNumber": number}


def make_source_db(directory, rows, columns=SOURCE_COLUMNS):
    """Write rows into <directory>/sqlite/open-mastr.db (table units_wind) and return its path."""
    path = Path(directory) / "sqlite" / "open-mastr.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    quoted = ", ".join(f'"{column}"' for column in columns)
    connection.execute(f"CREATE TABLE units_wind ({quoted})")
    connection.executemany(
        f"INSERT INTO units_wind VALUES ({', '.join('?' * len(columns))})",
        [[row.get(column) for column in columns] for row in rows],
    )
    connection.commit()
    connection.close()      # Windows: release the file so the temp folder can be deleted
    return path
