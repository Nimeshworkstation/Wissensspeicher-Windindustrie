from django.db import models


class IndexedFile(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("indexed", "Indexed"),
        ("failed", "Failed"),
    ]

    path = models.CharField(max_length=1024, unique=True)
    content_hash = models.CharField(max_length=64)
    original_file = models.BinaryField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.path} ({self.status})"
