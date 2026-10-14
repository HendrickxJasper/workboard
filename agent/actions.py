"""What each ProposedAction type needs and how it executes (rule 5).

Claude only ever produces payloads. Validation and execution live here, after you approve.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError

from card.models import Card


@dataclass
class Clients:
    """Lazily built external clients, injectable in tests."""

    odoo: object = None
    gmail: object = None

    def get_odoo(self):
        if self.odoo is None:
            from connector.odoo import OdooClient

            self.odoo = OdooClient.from_settings()
        return self.odoo

    def get_gmail(self):
        if self.gmail is None:
            from connector.gmail import GmailClient

            self.gmail = GmailClient.from_settings()
        return self.gmail


REQUIRED = {
    "odoo_create_ticket": ["name", "description"],
    "odoo_post_note": ["body"],
    "gmail_create_draft": ["to", "subject", "body"],
    "create_todo": ["title"],
}

PAYLOAD_HELP = {
    "odoo_create_ticket": {
        "name": "ticket title",
        "description": "customer issue, plain text",
        "partner_id": "Odoo res.partner id of the customer (int)",
        "team_id": "helpdesk.team id (optional; the configured support team wins)",
        "priority": "'0' low … '3' urgent",
    },
    "odoo_post_note": {
        "model": "Odoo model (default helpdesk.ticket)",
        "res_id": "record id, or null when depends_on a ticket being created",
        "body": "internal note: analysis and proposed solution, plain text",
    },
    "gmail_create_draft": {
        "thread_id": "Gmail thread id to reply in (optional)",
        "to": "recipient email",
        "subject": "subject",
        "body": "plain text; may use {depends_on_id} and {depends_on_url}",
        "in_reply_to": "Message-ID header to reply to (optional)",
    },
    "create_todo": {"title": "to-do title", "note": "details", "due_date": "YYYY-MM-DD (optional)"},
}


def validate_payload(action_type: str, payload: dict) -> dict:
    if action_type not in REQUIRED:
        raise ValidationError(f"Unknown action type {action_type!r}.")
    if not isinstance(payload, dict):
        raise ValidationError("Payload must be a JSON object.")
    missing = [k for k in REQUIRED[action_type] if not payload.get(k)]
    if missing:
        raise ValidationError(f"Missing {', '.join(missing)}.")
    if action_type == "create_todo" and payload.get("due_date"):
        try:
            date.fromisoformat(str(payload["due_date"]))
        except ValueError as exc:
            raise ValidationError("due_date must be YYYY-MM-DD.") from exc
    return payload


def _fill(text: str, dep_result: dict) -> str:
    return (
        str(text)
        .replace("{depends_on_id}", str(dep_result.get("id", "")))
        .replace("{depends_on_url}", dep_result.get("url", ""))
    )


def execute(action, clients: Clients) -> dict:
    """Run one approved action against the outside world. Returns the result dict."""
    payload = validate_payload(action.action_type, action.payload)
    dep_result = action.depends_on.result if action.depends_on_id else {}

    if action.action_type == "odoo_create_ticket":
        odoo = clients.get_odoo()
        vals = {"name": payload["name"], "description": payload["description"]}
        if payload.get("partner_id"):
            vals["partner_id"] = int(payload["partner_id"])
        team_id = settings.ODOO_SUPPORT_TEAM_ID or payload.get("team_id")
        if team_id:
            vals["team_id"] = int(team_id)
        if payload.get("priority") in ("0", "1", "2", "3"):
            vals["priority"] = payload["priority"]
        ticket_id = odoo.create("helpdesk.ticket", vals)
        return {
            "model": "helpdesk.ticket",
            "id": ticket_id,
            "url": odoo.record_url("helpdesk.ticket", ticket_id),
        }

    if action.action_type == "odoo_post_note":
        odoo = clients.get_odoo()
        model = payload.get("model") or dep_result.get("model") or "helpdesk.ticket"
        res_id = payload.get("res_id") or dep_result.get("id")
        if not res_id:
            raise ValidationError("No record to post on: set res_id or depend on a created ticket.")
        message_id = odoo.message_post(model, int(res_id), _fill(payload["body"], dep_result))
        return {
            "model": model,
            "id": int(res_id),
            "message_id": message_id,
            "url": odoo.record_url(model, int(res_id)),
        }

    if action.action_type == "gmail_create_draft":
        gmail = clients.get_gmail()
        return gmail.create_draft(
            thread_id=payload.get("thread_id", ""),
            to=payload["to"],
            subject=_fill(payload["subject"], dep_result),
            body=_fill(payload["body"], dep_result),
            in_reply_to=payload.get("in_reply_to", ""),
        )

    if action.action_type == "create_todo":
        todo = Card.objects.create(
            source=Card.Source.MANUAL,
            title=_fill(payload["title"], dep_result)[:300],
            excerpt=_fill(payload.get("note", ""), dep_result),
            due_date=date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None,
            client=action.card.client,
            column=Card.Column.WAITING_ME,
        )
        return {"card_id": todo.pk}

    raise ValidationError(f"Unknown action type {action.action_type!r}.")
