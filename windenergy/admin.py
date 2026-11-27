from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from windenergy.models import CatalogQuestion, QuerySuggestion, WindTurbine


@admin.register(WindTurbine)
class WindTurbineAdmin(admin.ModelAdmin):
    list_display = (
        "unit_mastr_number",
        "state",
        "municipality",
        "operational_status",
        "commissioning_date",
        "gross_capacity_mw",
        "manufacturer",
    )
    list_filter = ("state", "operational_status", "wind_onshore_or_offshore")
    search_fields = (
        "unit_mastr_number",
        "manufacturer",
        "model_designation",
        "municipality",
        "wind_farm_name",
    )
    readonly_fields = ("imported_at",)
    ordering = ("state", "municipality", "unit_mastr_number")
    list_per_page = 50


class CatalogQuestionForm(forms.ModelForm):
    class Meta:
        model = CatalogQuestion
        fields = "__all__"
        widgets = {
            "sql": forms.Textarea(attrs={
                "rows": 18, "cols": 110,
                "style": "font-family: Consolas, monospace; font-size: 13px;",
            }),
            "notes": forms.Textarea(attrs={"rows": 3, "cols": 110}),
        }


@admin.register(CatalogQuestion)
class CatalogQuestionAdmin(admin.ModelAdmin):
    form = CatalogQuestionForm
    list_display = ("code", "title", "is_active", "sort_order", "updated_at", "open_on_page")
    list_display_links = ("code", "title")
    list_editable = ("is_active", "sort_order")
    search_fields = ("code", "title", "sql")
    readonly_fields = ("updated_at",)
    fieldsets = (
        (None, {"fields": ("code", "title", "purpose", "is_active", "sort_order")}),
        ("Abfrage", {"fields": ("sql",)}),
        ("Darstellung", {"fields": ("chart_label", "chart_value", "notes")}),
        ("Info", {"fields": ("updated_at",)}),
    )

    @admin.display(description="Seite")
    def open_on_page(self, obj):
        return format_html(
            '<a href="{}?q={}" target="_blank">Ausführen</a>', reverse("questions"), obj.code
        )


@admin.register(QuerySuggestion)
class QuerySuggestionAdmin(admin.ModelAdmin):
    list_display = ("question", "status", "submitted_at")
    list_filter = ("status", "submitted_at")
    search_fields = ("question", "details", "developer_notes")
    readonly_fields = ("submitted_at",)
    ordering = ("-submitted_at",)
    fieldsets = (
        (None, {"fields": ("question", "details", "submitted_at", "status")}),
        ("Developer notes", {"fields": ("developer_notes",)}),
    )
