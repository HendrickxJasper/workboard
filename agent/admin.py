from django.contrib import admin

from .models import AgentRun, ProposedAction


class ProposedActionInline(admin.TabularInline):
    model = ProposedAction
    fk_name = "run"
    extra = 0
    fields = ["sequence", "action_type", "title", "status", "depends_on"]
    readonly_fields = fields


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "card",
        "kind",
        "status",
        "current_step",
        "started_at",
        "input_tokens",
        "output_tokens",
    ]
    list_filter = ["status", "kind"]
    raw_id_fields = ["card"]
    inlines = [ProposedActionInline]


@admin.register(ProposedAction)
class ProposedActionAdmin(admin.ModelAdmin):
    list_display = ["__str__", "card", "action_type", "status", "executed_at"]
    list_filter = ["status", "action_type"]
    raw_id_fields = ["run", "card", "depends_on"]
