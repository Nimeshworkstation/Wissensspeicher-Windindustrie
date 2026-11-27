from django.contrib import admin

from .models import IndexedFile


@admin.register(IndexedFile)
class IndexedFileAdmin(admin.ModelAdmin):
    list_display = ("id", "filename", "status", "content_hash", "updated_at")
    list_filter = ("status",)
    search_fields = ("path", "content_hash", "error")
    readonly_fields = ("content_hash", "updated_at")
    exclude = ("original_file",)

    @admin.display(description="Filename")
    def filename(self, obj):
        from pathlib import Path

        return Path(obj.path).name
