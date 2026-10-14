from django.db import models
from django.db.models import Q

from core.models import BaseModel


class AgentRun(BaseModel):
    class Kind(models.TextChoices):
        TRIAGE = "triage", "Triage"
        DRAFT = "draft", "Draft"
        RETRO = "retro", "Retro"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    ACTIVE_STATUSES = (Status.QUEUED, Status.RUNNING)

    card = models.ForeignKey("card.Card", on_delete=models.CASCADE, related_name="runs")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    current_step = models.CharField(max_length=200, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    skills_used = models.ManyToManyField("skill.Skill", blank=True, related_name="runs")
    model = models.CharField(max_length=100, blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    transcript = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["card"],
                condition=Q(status__in=["queued", "running"]),
                name="one_active_run_per_card",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk} ({self.status})"

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES


class ProposedAction(BaseModel):
    class Type(models.TextChoices):
        ODOO_CREATE_TICKET = "odoo_create_ticket", "Create Odoo ticket"
        ODOO_POST_NOTE = "odoo_post_note", "Post Odoo note"
        GMAIL_CREATE_DRAFT = "gmail_create_draft", "Create Gmail draft"
        CREATE_TODO = "create_todo", "Create to-do"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXECUTED = "executed", "Executed"
        FAILED = "failed", "Failed"

    OPEN_STATUSES = (Status.PROPOSED, Status.APPROVED, Status.FAILED)

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="actions")
    card = models.ForeignKey("card.Card", on_delete=models.CASCADE, related_name="actions")
    sequence = models.PositiveSmallIntegerField(default=0)
    action_type = models.CharField(max_length=30, choices=Type.choices)
    title = models.CharField(max_length=200, blank=True, default="")
    payload = models.JSONField(default=dict)
    depends_on = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="dependents"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROPOSED)
    result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["run", "sequence"]

    def __str__(self):
        return self.title or self.get_action_type_display()
