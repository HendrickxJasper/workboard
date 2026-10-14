from django.db import models

from core.models import BaseModel


class Connection(BaseModel):
    class Kind(models.TextChoices):
        GMAIL = "gmail", "Gmail"
        ODOO = "odoo", "Odoo"
        FILES = "files", "Files"

    kind = models.CharField(max_length=20, choices=Kind.choices, unique=True)
    name = models.CharField(max_length=100)
    config = models.JSONField(default=dict, blank=True, help_text="Non-secret settings and cached ids.")
    sync_cursor = models.JSONField(default=dict, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["kind"]

    def __str__(self):
        return self.name
