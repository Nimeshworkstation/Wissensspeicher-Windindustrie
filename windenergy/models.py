from django.db import models


class WindTurbine(models.Model):
    class State(models.TextChoices):
        BADEN_WUERTTEMBERG = "Baden-W\u00fcrttemberg", "Baden-W\u00fcrttemberg"
        BAYERN = "Bayern", "Bayern"
        BERLIN = "Berlin", "Berlin"
        BRANDENBURG = "Brandenburg", "Brandenburg"
        BREMEN = "Bremen", "Bremen"
        HAMBURG = "Hamburg", "Hamburg"
        HESSEN = "Hessen", "Hessen"
        MECKLENBURG_VORPOMMERN = "Mecklenburg-Vorpommern", "Mecklenburg-Vorpommern"
        NIEDERSACHSEN = "Niedersachsen", "Niedersachsen"
        NORDRHEIN_WESTFALEN = "Nordrhein-Westfalen", "Nordrhein-Westfalen"
        RHEINLAND_PFALZ = "Rheinland-Pfalz", "Rheinland-Pfalz"
        SAARLAND = "Saarland", "Saarland"
        SACHSEN = "Sachsen", "Sachsen"
        SACHSEN_ANHALT = "Sachsen-Anhalt", "Sachsen-Anhalt"
        SCHLESWIG_HOLSTEIN = "Schleswig-Holstein", "Schleswig-Holstein"
        THUERINGEN = "Th\u00fcringen", "Th\u00fcringen"
        EXCLUSIVE_ECONOMIC_ZONE = (
            "Ausschlie\u00dfliche Wirtschaftszone",
            "Ausschlie\u00dfliche Wirtschaftszone",
        )

    class OperationalStatus(models.TextChoices):
        IN_OPERATION = "In Betrieb", "In Betrieb"
        PLANNED = "In Planung", "In Planung"
        TEMPORARILY_SHUT_DOWN = "Vor\u00fcbergehend stillgelegt", "Vor\u00fcbergehend stillgelegt"
        PERMANENTLY_SHUT_DOWN = "Endg\u00fcltig stillgelegt", "Endg\u00fcltig stillgelegt"

    class WindType(models.TextChoices):
        ONSHORE = "Windenergie an Land", "Onshore"    # value = MaStR text, label = display
        OFFSHORE = "Windenergie auf See", "Offshore"

    # The non-federal EEZ entry is last and is excluded from the Bundesländer filter.
    FEDERAL_STATES = tuple(State.values[:-1])
    DEFAULT_STATES = (
        "Schleswig-Holstein",
        "Hamburg",
        "Bremen",
        "Niedersachsen",
        "Mecklenburg-Vorpommern",
    )
    MIN_REPOWERING_AGE_YEARS = 20
    UNKNOWN_MANUFACTURER = "Unbekannt"
    DEFAULT_STATUSES = (OperationalStatus.IN_OPERATION,)
    DEFAULT_WIND_TYPES = (WindType.ONSHORE,)

    unit_mastr_number = models.CharField(max_length=32, primary_key=True)
    location_mastr_number = models.CharField(max_length=32, blank=True)

    state = models.CharField(max_length=100, choices=State.choices, blank=True)
    district = models.CharField(max_length=150, blank=True)
    municipality = models.CharField(max_length=150, blank=True)
    municipality_key = models.CharField(max_length=32, blank=True)
    postal_code = models.CharField(max_length=16, blank=True)
    place = models.CharField(max_length=200, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    registration_date = models.DateField(null=True, blank=True)
    commissioning_date = models.DateField(null=True, blank=True)
    commissioning_date_at_current_location = models.DateField(null=True, blank=True)
    final_shutdown_date = models.DateField(null=True, blank=True)

    system_status = models.CharField(max_length=100, blank=True)
    operational_status = models.CharField(
        max_length=100,
        choices=OperationalStatus.choices,
        blank=True,
    )
    energy_source = models.CharField(max_length=100, blank=True)
    gross_capacity_mw = models.FloatField(null=True, blank=True)
    net_capacity_mw = models.FloatField(null=True, blank=True)

    manufacturer = models.CharField(max_length=200, blank=True)
    technology = models.CharField(max_length=150, blank=True)
    model_designation = models.CharField(max_length=200, blank=True)
    hub_height_m = models.FloatField(null=True, blank=True)
    rotor_diameter_m = models.FloatField(null=True, blank=True)
    wind_farm_name = models.CharField(max_length=200, blank=True)
    wind_onshore_or_offshore = models.CharField(max_length=50, blank=True)

    source_last_update = models.CharField(max_length=40, blank=True)
    source_download_date = models.CharField(max_length=40, blank=True)
    imported_at = models.DateTimeField()

    class Meta:
        ordering = ("state", "municipality", "unit_mastr_number")
        indexes = [
            models.Index(
                fields=("state", "operational_status", "commissioning_date"),
                name="wind_state_status_date_idx",
            ),
        ]

    def __str__(self):
        return f"{self.unit_mastr_number} — {self.manufacturer or 'Unbekannter Hersteller'}"


class CatalogQuestion(models.Model):
    """A question for the "Repowering-Analyse" page, managed in Django admin.

    The SQL is stored as plain text. It is only executed by the view
    (windenergy/queries.py), which allows SELECT/WITH statements only and runs
    them on a read-only SQLite connection state.
    """

    code = models.CharField(
        max_length=10, unique=True, help_text="Kurzes Kürzel, z. B. Q7."
    )
    title = models.CharField("Frage", max_length=300)
    purpose = models.CharField("Zweck", max_length=300, blank=True)
    sql = models.TextField(
        "SQL",
        help_text=(
            "Nur SELECT/WITH. Platzhalter: {base_filter} = gewählte Bundesländer "
            "und Inbetriebnahme bis Stichtag minus 20 Jahre; {states} = Liste der "
            "gewählten Bundesländer; %(cutoff)s = Stichtag minus 20 Jahre; "
            "%(horizon)s = Stichtag minus 15 Jahre; %(reference_date)s = Stichtag. "
            "Basis-View: v_repowering_candidates."
        ),
    )
    chart_label = models.CharField(
        "Diagramm: Beschriftungsspalte", max_length=100, blank=True,
        help_text="Spaltenname für die Balkenbeschriftung. Leer = kein Diagramm.",
    )
    chart_value = models.CharField(
        "Diagramm: Wertespalte", max_length=100, blank=True,
        help_text="Numerische Spalte für die Balkenlänge, z. B. leistung_mw.",
    )
    notes = models.TextField(
        "Hinweise", blank=True, help_text="Ein Hinweis pro Zeile, wird über dem Ergebnis angezeigt."
    )
    is_active = models.BooleanField("Aktiv", default=True)
    sort_order = models.PositiveIntegerField("Reihenfolge", default=100)
    updated_at = models.DateTimeField("Geändert am", auto_now=True)

    class Meta:
        ordering = ("sort_order", "code")
        verbose_name = "Katalogfrage"
        verbose_name_plural = "Katalogfragen"

    def __str__(self):
        return f"{self.code} – {self.title}"

    @property
    def note_list(self):
        return [line.strip() for line in self.notes.splitlines() if line.strip()]


class QuerySuggestion(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Neu"
        REVIEWING = "reviewing", "Wird geprüft"
        IMPLEMENTED = "implemented", "Umgesetzt"
        DECLINED = "declined", "Nicht geplant"

    question = models.CharField("Gewünschte Frage", max_length=500)
    details = models.TextField("Zusätzliche Hinweise", blank=True)
    status = models.CharField(
        "Status", max_length=16, choices=Status.choices, default=Status.NEW
    )
    developer_notes = models.TextField("Interne Notizen", blank=True)
    submitted_at = models.DateTimeField("Eingereicht am", auto_now_add=True)

    class Meta:
        ordering = ("-submitted_at",)
        verbose_name = "Abfragevorschlag"
        verbose_name_plural = "Abfragevorschläge"

    def __str__(self):
        return self.question[:80]
