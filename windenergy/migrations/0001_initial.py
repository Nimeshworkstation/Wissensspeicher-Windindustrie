"""Initial schema of the windenergy app, in one migration.

Besides the tables this migration creates three things that makemigrations
cannot generate on its own:
  1. the daily 03:00 MaStR refresh schedule for Celery Beat,
  2. the database view v_repowering_candidates (the shared rule of the lead
     question: onshore, in operation, commissioning date present),
  3. the starter questions Q1-Q6 of the SQL catalogue.
"""

from django.db import migrations, models


# --- 1. Daily MaStR refresh schedule (Celery Beat) -------------------------


SCHEDULE_NAME = "Daily MaStR wind data refresh"


def create_schedule(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="0",
        hour="3",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Europe/Berlin",
    )
    PeriodicTask.objects.update_or_create(
        name=SCHEDULE_NAME,
        defaults={
            "task": "windenergy.refresh_mastr_wind_data",
            "crontab": schedule,
            "enabled": True,
            "description": "Download MaStR wind data and import it into the Django database.",
        },
    )


def remove_schedule(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=SCHEDULE_NAME).delete()


# --- 2. View with the shared rule of the lead question ----------------------


CREATE_VIEW = """
CREATE VIEW v_repowering_candidates AS
SELECT *
FROM windenergy_windturbine
WHERE wind_onshore_or_offshore = 'Windenergie an Land'
  AND operational_status = 'In Betrieb'
  AND commissioning_date IS NOT NULL
"""


DROP_VIEW = "DROP VIEW IF EXISTS v_repowering_candidates"


# --- 3. Starter questions of the SQL catalogue -----------------------------


QUESTIONS = [
    {
        "code": "Q1",
        "sort_order": 10,
        "title": "Wie viele Anlagen sind zum Stichtag älter als 20 Jahre – je Bundesland?",
        "purpose": "Leitfrage: Wo liegt das Repowering-Potenzial?",
        "chart_label": "bundesland",
        "chart_value": "leistung_mw",
        "sql": """SELECT state                                     AS bundesland,
       COUNT(*)                                  AS anlagen,
       ROUND(SUM(gross_capacity_mw) / 1000.0, 1) AS leistung_mw,
       MIN(commissioning_date)                   AS aelteste_inbetriebnahme
FROM v_repowering_candidates
WHERE {base_filter}
GROUP BY state
ORDER BY leistung_mw DESC""",
    },
    {
        "code": "Q2",
        "sort_order": 20,
        "title": "Von welchen Herstellern stammen diese Anlagen und mit welcher Leistung?",
        "purpose": "Leitfrage: Hersteller und Leistung.",
        "chart_label": "hersteller",
        "chart_value": "leistung_mw",
        "notes": (
            "Herstellernamen sind noch nicht normalisiert (z. B. erscheint Nordex "
            "unter drei Firmennamen). Siehe IMPROVEMENTS.txt, Punkt 2.1."
        ),
        "sql": """SELECT CASE WHEN manufacturer = '' THEN 'Unbekannt' ELSE manufacturer END AS hersteller,
       COUNT(*)                                  AS anlagen,
       ROUND(SUM(gross_capacity_mw) / 1000.0, 1) AS leistung_mw,
       ROUND(100.0 * SUM(gross_capacity_mw)
             / SUM(SUM(gross_capacity_mw)) OVER (), 1) AS anteil_leistung_prozent
FROM v_repowering_candidates
WHERE {base_filter}
GROUP BY hersteller
ORDER BY leistung_mw DESC""",
    },
    {
        "code": "Q3",
        "sort_order": 30,
        "title": "Welche Anlagen sind es? (Einzelliste, vollständig als CSV)",
        "purpose": "Leitfrage: Welche Anlagen – prüfbar über die MaStR-Nummer.",
        "sql": """SELECT unit_mastr_number                    AS mastr_nr,
       state                                AS bundesland,
       district                             AS landkreis,
       municipality                         AS gemeinde,
       CASE WHEN manufacturer = '' THEN 'Unbekannt' ELSE manufacturer END AS hersteller,
       model_designation                    AS typ,
       commissioning_date                   AS inbetriebnahme,
       ROUND(gross_capacity_mw / 1000.0, 3) AS leistung_mw,
       hub_height_m                         AS nabenhoehe_m,
       rotor_diameter_m                     AS rotordurchmesser_m,
       latitude                             AS breitengrad,
       longitude                            AS laengengrad
FROM v_repowering_candidates
WHERE {base_filter}
ORDER BY commissioning_date, unit_mastr_number""",
    },
    {
        "code": "Q4",
        "sort_order": 40,
        "title": "In welchen Landkreisen liegt die meiste alte Leistung?",
        "purpose": "Präzisiert das „Wo“ der Leitfrage auf Kreisebene (Top 20).",
        "chart_label": "landkreis",
        "chart_value": "leistung_mw",
        "sql": """SELECT state                                     AS bundesland,
       CASE WHEN district = '' THEN 'Unbekannt' ELSE district END AS landkreis,
       COUNT(*)                                  AS anlagen,
       ROUND(SUM(gross_capacity_mw) / 1000.0, 1) AS leistung_mw
FROM v_repowering_candidates
WHERE {base_filter}
GROUP BY state, landkreis
ORDER BY leistung_mw DESC
LIMIT 20""",
    },
    {
        "code": "Q5",
        "sort_order": 50,
        "title": "Wann erreichen die Anlagen die 20-Jahre-Grenze? (Repowering-Wellen)",
        "purpose": (
            "Zeigt je Inbetriebnahmejahr, welche Leistung im Bestand ist – auch die "
            "Jahrgänge, die in den 5 Jahren nach dem Stichtag 20 Jahre alt werden."
        ),
        "chart_label": "inbetriebnahmejahr",
        "chart_value": "leistung_mw",
        "notes": (
            "Grundlage ist das MaStR-Inbetriebnahmedatum der Einheit. Das für das "
            "EEG-Förderende maßgebliche EEG-Inbetriebnahmedatum kann abweichen "
            "(Tabelle AnlagenEegWind, noch nicht importiert)."
        ),
        "sql": """SELECT CAST(SUBSTR(commissioning_date, 1, 4) AS INTEGER)      AS inbetriebnahmejahr,
       CAST(SUBSTR(commissioning_date, 1, 4) AS INTEGER) + 20 AS jahr_20_jahre_alt,
       COUNT(*)                                  AS anlagen,
       ROUND(SUM(gross_capacity_mw) / 1000.0, 1) AS leistung_mw,
       CASE WHEN MAX(commissioning_date) <= %(cutoff)s
            THEN 'ja' ELSE 'nein' END            AS zum_stichtag_ueber_20_jahre
FROM v_repowering_candidates
WHERE state IN ({states})
  AND commissioning_date <= %(horizon)s
GROUP BY inbetriebnahmejahr
ORDER BY inbetriebnahmejahr""",
    },
    {
        "code": "Q6",
        "sort_order": 60,
        "title": "Welche Anlagentypen sind unter den alten Anlagen am häufigsten?",
        "purpose": "Basis für Repowering-Angebote: Welche Typen werden ersetzt? (Top 20)",
        "notes": (
            "Typbezeichnungen sind noch nicht normalisiert (z. B. „N117“, "
            "„N117/2400“). Siehe IMPROVEMENTS.txt, Punkt 2.2."
        ),
        "sql": """SELECT CASE WHEN manufacturer = '' THEN 'Unbekannt' ELSE manufacturer END AS hersteller,
       CASE WHEN model_designation = '' THEN 'Unbekannt' ELSE model_designation END AS typ,
       COUNT(*)                                  AS anlagen,
       ROUND(SUM(gross_capacity_mw) / 1000.0, 1) AS leistung_mw,
       ROUND(AVG(hub_height_m), 1)               AS mittlere_nabenhoehe_m,
       ROUND(AVG(rotor_diameter_m), 1)           AS mittlerer_rotordurchmesser_m
FROM v_repowering_candidates
WHERE {base_filter}
GROUP BY hersteller, typ
ORDER BY anlagen DESC
LIMIT 20""",
    },
]


def seed(apps, schema_editor):
    CatalogQuestion = apps.get_model("windenergy", "CatalogQuestion")
    for question in QUESTIONS:
        defaults = {key: value for key, value in question.items() if key != "code"}
        CatalogQuestion.objects.get_or_create(code=question["code"], defaults=defaults)


def unseed(apps, schema_editor):
    CatalogQuestion = apps.get_model("windenergy", "CatalogQuestion")
    CatalogQuestion.objects.filter(code__in=[q["code"] for q in QUESTIONS]).delete()


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [
        migrations.CreateModel(
            name='CatalogQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(help_text='Kurzes Kürzel, z. B. Q7.', max_length=10, unique=True)),
                ('title', models.CharField(max_length=300, verbose_name='Frage')),
                ('purpose', models.CharField(blank=True, max_length=300, verbose_name='Zweck')),
                ('sql', models.TextField(help_text='Nur SELECT/WITH. Platzhalter: {base_filter} = gewählte Bundesländer und Inbetriebnahme bis Stichtag minus 20 Jahre; {states} = Liste der gewählten Bundesländer; %(cutoff)s = Stichtag minus 20 Jahre; %(horizon)s = Stichtag minus 15 Jahre; %(reference_date)s = Stichtag. Basis-View: v_repowering_candidates.', verbose_name='SQL')),
                ('chart_label', models.CharField(blank=True, help_text='Spaltenname für die Balkenbeschriftung. Leer = kein Diagramm.', max_length=100, verbose_name='Diagramm: Beschriftungsspalte')),
                ('chart_value', models.CharField(blank=True, help_text='Numerische Spalte für die Balkenlänge, z. B. leistung_mw.', max_length=100, verbose_name='Diagramm: Wertespalte')),
                ('notes', models.TextField(blank=True, help_text='Ein Hinweis pro Zeile, wird über dem Ergebnis angezeigt.', verbose_name='Hinweise')),
                ('is_active', models.BooleanField(default=True, verbose_name='Aktiv')),
                ('sort_order', models.PositiveIntegerField(default=100, verbose_name='Reihenfolge')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Geändert am')),
            ],
            options={
                'verbose_name': 'Katalogfrage',
                'verbose_name_plural': 'Katalogfragen',
                'ordering': ('sort_order', 'code'),
            },
        ),
        migrations.CreateModel(
            name='QuerySuggestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('question', models.CharField(max_length=500, verbose_name='Gewünschte Frage')),
                ('details', models.TextField(blank=True, verbose_name='Zusätzliche Hinweise')),
                ('status', models.CharField(choices=[('new', 'Neu'), ('reviewing', 'Wird geprüft'), ('implemented', 'Umgesetzt'), ('declined', 'Nicht geplant')], default='new', max_length=16, verbose_name='Status')),
                ('developer_notes', models.TextField(blank=True, verbose_name='Interne Notizen')),
                ('submitted_at', models.DateTimeField(auto_now_add=True, verbose_name='Eingereicht am')),
            ],
            options={
                'verbose_name': 'Abfragevorschlag',
                'verbose_name_plural': 'Abfragevorschläge',
                'ordering': ('-submitted_at',),
            },
        ),
        migrations.CreateModel(
            name='WindTurbine',
            fields=[
                ('unit_mastr_number', models.CharField(max_length=32, primary_key=True, serialize=False)),
                ('location_mastr_number', models.CharField(blank=True, max_length=32)),
                ('state', models.CharField(blank=True, choices=[('Baden-Württemberg', 'Baden-Württemberg'), ('Bayern', 'Bayern'), ('Berlin', 'Berlin'), ('Brandenburg', 'Brandenburg'), ('Bremen', 'Bremen'), ('Hamburg', 'Hamburg'), ('Hessen', 'Hessen'), ('Mecklenburg-Vorpommern', 'Mecklenburg-Vorpommern'), ('Niedersachsen', 'Niedersachsen'), ('Nordrhein-Westfalen', 'Nordrhein-Westfalen'), ('Rheinland-Pfalz', 'Rheinland-Pfalz'), ('Saarland', 'Saarland'), ('Sachsen', 'Sachsen'), ('Sachsen-Anhalt', 'Sachsen-Anhalt'), ('Schleswig-Holstein', 'Schleswig-Holstein'), ('Thüringen', 'Thüringen'), ('Ausschließliche Wirtschaftszone', 'Ausschließliche Wirtschaftszone')], max_length=100)),
                ('district', models.CharField(blank=True, max_length=150)),
                ('municipality', models.CharField(blank=True, max_length=150)),
                ('municipality_key', models.CharField(blank=True, max_length=32)),
                ('postal_code', models.CharField(blank=True, max_length=16)),
                ('place', models.CharField(blank=True, max_length=200)),
                ('latitude', models.FloatField(blank=True, null=True)),
                ('longitude', models.FloatField(blank=True, null=True)),
                ('registration_date', models.DateField(blank=True, null=True)),
                ('commissioning_date', models.DateField(blank=True, null=True)),
                ('commissioning_date_at_current_location', models.DateField(blank=True, null=True)),
                ('final_shutdown_date', models.DateField(blank=True, null=True)),
                ('system_status', models.CharField(blank=True, max_length=100)),
                ('operational_status', models.CharField(blank=True, choices=[('In Betrieb', 'In Betrieb'), ('In Planung', 'In Planung'), ('Vorübergehend stillgelegt', 'Vorübergehend stillgelegt'), ('Endgültig stillgelegt', 'Endgültig stillgelegt')], max_length=100)),
                ('energy_source', models.CharField(blank=True, max_length=100)),
                ('gross_capacity_mw', models.FloatField(blank=True, null=True)),
                ('net_capacity_mw', models.FloatField(blank=True, null=True)),
                ('manufacturer', models.CharField(blank=True, max_length=200)),
                ('technology', models.CharField(blank=True, max_length=150)),
                ('model_designation', models.CharField(blank=True, max_length=200)),
                ('hub_height_m', models.FloatField(blank=True, null=True)),
                ('rotor_diameter_m', models.FloatField(blank=True, null=True)),
                ('wind_farm_name', models.CharField(blank=True, max_length=200)),
                ('wind_onshore_or_offshore', models.CharField(blank=True, max_length=50)),
                ('source_last_update', models.CharField(blank=True, max_length=40)),
                ('source_download_date', models.CharField(blank=True, max_length=40)),
                ('imported_at', models.DateTimeField()),
            ],
            options={
                'ordering': ('state', 'municipality', 'unit_mastr_number'),
                'indexes': [models.Index(fields=['state', 'operational_status', 'commissioning_date'], name='wind_state_status_date_idx')],
            },
        ),
        # Created after the tables (see module docstring).
        migrations.RunPython(create_schedule, remove_schedule),
        migrations.RunSQL(CREATE_VIEW, DROP_VIEW),
        migrations.RunPython(seed, unseed),
    ]
