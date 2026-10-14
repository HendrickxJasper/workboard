from datetime import timedelta

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from core.models import BaseModel


class Client(BaseModel):
    name = models.CharField(max_length=200)
    odoo_partner_id = models.IntegerField(null=True, blank=True, unique=True)
    email_domains = ArrayField(models.CharField(max_length=200), default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CardQuerySet(models.QuerySet):
    def with_activity(self):
        if "has_active_run" in self.query.annotations:
            return self
        from agent.models import AgentRun, ProposedAction

        active_runs = AgentRun.objects.filter(card=OuterRef("pk"), status__in=AgentRun.ACTIVE_STATUSES)
        pending = ProposedAction.objects.filter(card=OuterRef("pk"), status=ProposedAction.Status.PROPOSED)
        return self.annotate(has_active_run=Exists(active_runs), has_pending_actions=Exists(pending))

    def running(self):
        return self.with_activity().filter(Q(has_active_run=True) | Q(timer_running=True))

    def idle(self):
        threshold = timezone.now() - timedelta(days=settings.IDLE_AFTER_DAYS)
        return (
            self.with_activity()
            .filter(has_active_run=False, timer_running=False, last_activity_at__lt=threshold)
            .exclude(column=Card.Column.DONE)
        )


class Card(BaseModel):
    class Source(models.TextChoices):
        GMAIL = "gmail", "Mail"
        ODOO_TASK = "odoo_task", "Task"
        ODOO_TICKET = "odoo_ticket", "Ticket"
        ODOO_ACTIVITY = "odoo_activity", "Activity"
        FILE = "file", "File"
        MANUAL = "manual", "To-do"

    class Column(models.TextChoices):
        INBOX = "inbox", "Inbox"
        TRIAGED = "triaged", "Triaged"
        AI_DRAFTED = "ai_drafted", "AI drafted"
        WAITING_ME = "waiting_me", "Waiting on me"
        WAITING_OTHERS = "waiting_others", "Waiting on others"
        DONE = "done", "Done"

    class Urgency(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    source = models.CharField(max_length=20, choices=Source.choices)
    connection = models.ForeignKey(
        "connector.Connection", null=True, blank=True, on_delete=models.PROTECT, related_name="cards"
    )
    external_id = models.CharField(max_length=255, blank=True, default="")
    external_url = models.URLField(max_length=500, blank=True, default="")
    title = models.CharField(max_length=300)
    excerpt = models.TextField(blank=True, default="")
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.SET_NULL, related_name="cards")
    column = models.CharField(max_length=20, choices=Column.choices, default=Column.INBOX)
    position = models.PositiveIntegerField(default=0)
    urgency = models.CharField(max_length=10, choices=Urgency.choices, default=Urgency.NORMAL)
    due_date = models.DateField(null=True, blank=True)
    ai_assist_score = models.PositiveSmallIntegerField(null=True, blank=True)
    summary = models.TextField(blank=True, default="")
    next_step = models.TextField(blank=True, default="")
    timer_running = models.BooleanField(default=False)
    last_activity_at = models.DateTimeField(default=timezone.now)
    content_hash = models.CharField(max_length=64, blank=True, default="")
    raw = models.JSONField(default=dict, blank=True)

    objects = CardQuerySet.as_manager()

    class Meta:
        ordering = ["column", "position", "-last_activity_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id"],
                condition=~Q(source="manual"),
                name="card_unique_external",
            ),
        ]
        indexes = [models.Index(fields=["column", "position"])]

    def __str__(self):
        return self.title
