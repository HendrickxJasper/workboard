from django.contrib import admin

from .models import Skill, SkillRepo


@admin.register(SkillRepo)
class SkillRepoAdmin(admin.ModelAdmin):
    list_display = ["name", "remote_url", "is_shared", "last_pulled_at", "last_error"]


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ["slug", "category", "repo", "usage_count", "last_used_at"]
    list_filter = ["category", "repo"]
    search_fields = ["slug", "description"]
