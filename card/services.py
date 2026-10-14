"""Card business logic. Views and tasks call these; nothing here touches a request."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Card, Client

RUNNING, IDLE, ACTIVE = "running", "idle", "active"


# --- activity state (rule 6) ---------------------------------------------------
def activity_state(card: Card) -> str:
    has_run = getattr(card, "has_active_run", None)
    if has_run is None:
        from agent.models import AgentRun

        has_run = card.runs.filter(status__in=AgentRun.ACTIVE_STATUSES).exists()
    if has_run or card.timer_running:
        return RUNNING
    threshold = timezone.now() - timedelta(days=settings.IDLE_AFTER_DAYS)
    if card.column != Card.Column.DONE and card.last_activity_at < threshold:
        return IDLE
    return ACTIVE


def idle_days(card: Card) -> int:
    return (timezone.now() - card.last_activity_at).days


def counters() -> dict:
    from agent.models import ProposedAction

    return {
        "running": Card.objects.running().count(),
        "idle": Card.objects.idle().count(),
        "to_approve": ProposedAction.objects.filter(status=ProposedAction.Status.PROPOSED).count(),
    }


# --- board ---------------------------------------------------------------------
DONE_LIMIT = 25


def board_columns(*, client_id=None, source=None, state=None) -> list[dict]:
    qs = Card.objects.with_activity().select_related("client")
    if client_id:
        qs = qs.filter(client_id=client_id)
    if source:
        qs = qs.filter(source=source)
    if state == RUNNING:
        qs = qs.running()
    elif state == IDLE:
        qs = qs.idle()
    columns = []
    for value, label in Card.Column.choices:
        cards = qs.filter(column=value).order_by("position", "-last_activity_at")
        if value == Card.Column.DONE:
            cards = qs.filter(column=value).order_by("-updated_at")[:DONE_LIMIT]
        columns.append({"key": value, "label": label, "cards": list(cards)})
    return columns


# --- moving (rule 13) ----------------------------------------------------------
@transaction.atomic
def move_card(card: Card, column: str, position: int) -> Card:
    if column not in Card.Column.values:
        raise ValidationError(f"Unknown column {column!r}.")
    position = max(0, int(position))
    siblings = list(
        Card.objects.select_for_update()
        .filter(column=column)
        .exclude(pk=card.pk)
        .order_by("position", "-last_activity_at")
    )
    siblings.insert(min(position, len(siblings)), card)
    for index, item in enumerate(siblings):
        item.position = index
    Card.objects.bulk_update([c for c in siblings if c.pk != card.pk], ["position"])
    card.column = column
    card.last_activity_at = timezone.now()
    card.save(update_fields=["column", "position", "last_activity_at", "updated_at"])
    return card


def touch(card: Card):
    card.last_activity_at = timezone.now()
    card.save(update_fields=["last_activity_at", "updated_at"])


# --- source state (rule 2) -----------------------------------------------------
def apply_source_state(card: Card, *, closed: bool) -> Card:
    """Odoo records that closed (or left my open list) move to Done. Gmail never auto-closes."""
    if closed and card.source != Card.Source.GMAIL and card.column != Card.Column.DONE:
        card.column = Card.Column.DONE
        card.timer_running = False
        card.last_activity_at = timezone.now()
        card.save(update_fields=["column", "timer_running", "last_activity_at", "updated_at"])
    return card


# --- creating and upserting (rule 1, 3) ----------------------------------------
def content_hash(title: str, excerpt: str) -> str:
    return hashlib.sha256(json.dumps([title, excerpt], ensure_ascii=False).encode()).hexdigest()


UPSERT_FIELDS = ("title", "excerpt", "external_url", "due_date", "raw")


@transaction.atomic
def upsert_card(*, connection, source: str, external_id: str, data: dict) -> tuple[Card, bool]:
    """Create or update the card for one external record. Returns (card, content_changed)."""
    new_hash = content_hash(data.get("title", ""), data.get("excerpt", ""))
    card = Card.objects.select_for_update().filter(source=source, external_id=external_id).first()
    created = card is None
    if created:
        card = Card(source=source, external_id=external_id, connection=connection)
    for field in UPSERT_FIELDS:
        if field in data:
            setattr(card, field, data[field])
    if data.get("urgency") and (created or card.urgency == Card.Urgency.NORMAL):
        card.urgency = data["urgency"]
    if data.get("client") and not card.client_id:
        card.client = data["client"]
    if "timer_running" in data:
        card.timer_running = data["timer_running"]

    changed = created or card.content_hash != new_hash
    if changed:
        card.content_hash = new_hash
        card.last_activity_at = timezone.now()
        if not created and card.column == Card.Column.DONE and source == Card.Source.GMAIL:
            card.column = Card.Column.INBOX  # a new mail on a closed thread reopens it
    card.save()

    if changed and card.column == Card.Column.INBOX and settings.AUTO_TRIAGE:
        from agent.services import queue_run

        queue_run(card, "triage")
    return card, changed


def create_manual_card(
    *, title: str, column: str = Card.Column.INBOX, excerpt="", due_date=None, client=None
):
    if not title.strip():
        raise ValidationError("A to-do needs a title.")
    return Card.objects.create(
        source=Card.Source.MANUAL,
        title=title.strip()[:300],
        excerpt=excerpt,
        column=column,
        due_date=due_date,
        client=client,
    )


# --- clients -------------------------------------------------------------------
def client_for_email(email: str) -> Client | None:
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    if not domain:
        return None
    return Client.objects.filter(email_domains__contains=[domain]).first()


def client_for_partner(partner_id: int | None, name: str = "") -> Client | None:
    if not partner_id:
        return None
    client, _ = Client.objects.get_or_create(
        odoo_partner_id=partner_id, defaults={"name": name or f"#{partner_id}"}
    )
    return client
