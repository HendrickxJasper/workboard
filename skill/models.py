from django.db import models

from core.models import BaseModel


class SkillRepo(BaseModel):
    name = models.CharField(max_length=100)
    remote_url = models.CharField(max_length=500, blank=True, default="")
    local_path = models.CharField(max_length=500)
    default_branch = models.CharField(
        max_length=100, blank=True, default="", help_text="Empty = remote default."
    )
    is_shared = models.BooleanField(default=True, help_text="Shared repos only change through pull requests.")
    last_pulled_commit = models.CharField(max_length=40, blank=True, default="")
    last_pulled_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    def __str__(self):
        return self.name


class Skill(BaseModel):
    repo = models.ForeignKey(SkillRepo, on_delete=models.CASCADE, related_name="skills")
    slug = models.SlugField(max_length=100)
    category = models.CharField(max_length=100, blank=True, default="other")
    path = models.CharField(max_length=500, help_text="SKILL.md path relative to the repo root.")
    description = models.TextField(blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    usage_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["category", "slug"]
        constraints = [models.UniqueConstraint(fields=["repo", "slug"], name="skill_unique_slug")]

    def __str__(self):
        return self.slug
