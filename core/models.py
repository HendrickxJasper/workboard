from django.db import models


class BaseModel(models.Model):
    """Abstract base for every model: timestamps on create and update."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
