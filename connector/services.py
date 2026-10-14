"""Sync external sources into cards (rules 1 and 2).

Odoo: every run fetches *my open* tasks, tickets and activities in full. The sets are
small, and a full fetch lets us notice records that closed or were reassigned: those
cards move to Done. Gmail: a query-based poll; threads are never auto-closed.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date

from django.conf import settings
from django.utils import timezone

from card.models import Card
from card.services import apply_source_state, client_for_email, client_for_partner, upsert_card

from .gmail import GmailClient, thread_url
from .models import Connection
from .odoo import OdooClient, OdooError

log = logging.getLogger(__name__)
EXCERPT_CHARS = 1000


def get_connection(kind: str) -> Connection:
    conn, _ = Connection.objects.get_or_create(kind=kind, defaults={"name": Connection.Kind(kind).label})
    return conn


def strip_html(value) -> str:
    if not value:
        return ""
    text = re.sub(r"<(br|/p|/div|/li)\s*/?>", "\n", str(value), flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def _m2o(value):
    """Odoo many2one comes back as [id, display_name] or False."""
    return (value[0], value[1]) if isinstance(value, list) and value else (None, "")


def _date(value):
    return date.fromisoformat(value[:10]) if value else None


# --- Odoo ------------------------------------------------------------------------
def _odoo_uid(odoo: OdooClient, conn: Connection) -> int:
    login = settings.ODOO_LOGIN
    cached = conn.config.get("uid")
    if cached and conn.config.get("login") == login:
        return cached
    users = odoo.search_read("res.users", [("login", "=", login)], ["id"], limit=1)
    if not users:
        raise OdooError(f"No Odoo user with login {login!r}.")
    conn.config.update(uid=users[0]["id"], login=login)
    conn.save(update_fields=["config", "updated_at"])
    return users[0]["id"]


def _task_data(odoo, rec):
    partner_id, partner_name = _m2o(rec.get("partner_id"))
    _, project = _m2o(rec.get("project_id"))
    _, stage = _m2o(rec.get("stage_id"))
    return {
        "title": rec["name"],
        "excerpt": strip_html(rec.get("description"))[:EXCERPT_CHARS],
        "external_url": odoo.record_url("project.task", rec["id"]),
        "due_date": _date(rec.get("date_deadline")),
        "urgency": Card.Urgency.HIGH if rec.get("priority") == "1" else None,
        "client": client_for_partner(partner_id, partner_name),
        "raw": {"model": "project.task", "id": rec["id"], "project": project, "stage": stage},
    }


def _ticket_data(odoo, rec):
    partner_id, partner_name = _m2o(rec.get("partner_id"))
    _, team = _m2o(rec.get("team_id"))
    _, stage = _m2o(rec.get("stage_id"))
    priority = rec.get("priority") or "0"
    return {
        "title": rec["name"],
        "excerpt": strip_html(rec.get("description"))[:EXCERPT_CHARS],
        "external_url": odoo.record_url("helpdesk.ticket", rec["id"]),
        "urgency": Card.Urgency.HIGH if priority >= "2" else None,
        "client": client_for_partner(partner_id, partner_name),
        "raw": {"model": "helpdesk.ticket", "id": rec["id"], "team": team, "stage": stage},
    }


def _activity_data(odoo, rec):
    _, activity_type = _m2o(rec.get("activity_type_id"))
    title = rec.get("summary") or f"{activity_type}: {rec.get('res_name', '')}".strip(": ")
    return {
        "title": title or "Activity",
        "excerpt": strip_html(rec.get("note"))[:EXCERPT_CHARS],
        "external_url": odoo.record_url(rec["res_model"], rec["res_id"]) if rec.get("res_model") else "",
        "due_date": _date(rec.get("date_deadline")),
        "raw": {
            "model": "mail.activity",
            "id": rec["id"],
            "res_model": rec.get("res_model"),
            "res_id": rec.get("res_id"),
            "res_name": rec.get("res_name"),
            "type": activity_type,
        },
    }


def odoo_sources(uid: int):
    """(card source, model, domain, fields, mapper) for each Odoo record type we track."""
    return [
        (
            Card.Source.ODOO_TASK,
            "project.task",
            [("user_ids", "in", [uid]), ("state", "not in", ["1_done", "1_canceled"])],
            ["name", "description", "partner_id", "project_id", "stage_id", "date_deadline", "priority"],
            _task_data,
        ),
        (
            Card.Source.ODOO_TICKET,
            "helpdesk.ticket",
            [("user_id", "=", uid), ("stage_id.fold", "=", False)],
            ["name", "description", "partner_id", "team_id", "stage_id", "priority"],
            _ticket_data,
        ),
        (
            Card.Source.ODOO_ACTIVITY,
            "mail.activity",
            [("user_id", "=", uid)],
            ["summary", "note", "activity_type_id", "date_deadline", "res_model", "res_id", "res_name"],
            _activity_data,
        ),
    ]


TIMER_SOURCES = {"project.task": Card.Source.ODOO_TASK, "helpdesk.ticket": Card.Source.ODOO_TICKET}


def sync_odoo(odoo: OdooClient | None = None) -> dict:
    conn = get_connection(Connection.Kind.ODOO)
    stats = {"upserted": 0, "changed": 0, "closed": 0, "skipped": []}
    try:
        odoo = odoo or OdooClient.from_settings()
        uid = _odoo_uid(odoo, conn)
        for source, model, domain, fields, mapper in odoo_sources(uid):
            try:
                records = odoo.search_read(model, domain, fields)
            except OdooError as exc:
                if exc.status in (400, 404) or "does not exist" in str(exc).lower():
                    stats["skipped"].append(model)  # app not installed: skip, don't close anything
                    continue
                raise
            seen = set()
            for rec in records:
                external_id = str(rec["id"])
                seen.add(external_id)
                _, changed = upsert_card(
                    connection=conn, source=source, external_id=external_id, data=mapper(odoo, rec)
                )
                stats["upserted"] += 1
                stats["changed"] += int(changed)
            gone = (
                Card.objects.filter(source=source)
                .exclude(column=Card.Column.DONE)
                .exclude(external_id__in=seen)
            )
            for card in gone:
                apply_source_state(card, closed=True)
                stats["closed"] += 1
        _sync_timers(odoo, uid)
    except OdooError as exc:
        conn.last_error = str(exc)
        conn.save(update_fields=["last_error", "updated_at"])
        log.warning("Odoo sync failed: %s", exc)
        stats["error"] = str(exc)
        return stats
    conn.last_sync_at = timezone.now()
    conn.last_error = ", ".join(f"{m} not available" for m in stats["skipped"])
    conn.sync_cursor = {"stats": {k: v for k, v in stats.items() if k != "skipped"}}
    conn.save(update_fields=["last_sync_at", "last_error", "sync_cursor", "updated_at"])
    return stats


def _sync_timers(odoo: OdooClient, uid: int):
    """Mirror running Odoo timers (timer.timer) onto cards. Silently skipped if the model is absent."""
    try:
        timers = odoo.search_read(
            "timer.timer", [("user_id", "=", uid), ("timer_start", "!=", False)], ["res_model", "res_id"]
        )
    except OdooError:
        return
    running = {(t["res_model"], str(t["res_id"])) for t in timers}
    for model, source in TIMER_SOURCES.items():
        ids = [rid for m, rid in running if m == model]
        Card.objects.filter(source=source, timer_running=True).exclude(external_id__in=ids).update(
            timer_running=False
        )
        Card.objects.filter(source=source, external_id__in=ids).update(
            timer_running=True, last_activity_at=timezone.now()
        )


# --- Gmail -------------------------------------------------------------------------
def gmail_card_data(thread: dict) -> dict:
    sender = thread["from_name"] or thread["from_email"]
    return {
        "title": thread["subject"][:300],
        "excerpt": f"From {sender}: {thread['snippet']}"[:EXCERPT_CHARS],
        "external_url": thread_url(thread["thread_id"]),
        "client": client_for_email(thread["from_email"]),
        "raw": thread,
    }


def sync_gmail(gmail: GmailClient | None = None) -> dict:
    conn = get_connection(Connection.Kind.GMAIL)
    stats = {"upserted": 0, "changed": 0}
    try:
        gmail = gmail or GmailClient.from_settings()
        for thread_id in gmail.list_thread_ids(settings.GMAIL_QUERY, settings.GMAIL_MAX_THREADS):
            thread = gmail.get_thread(thread_id)
            if not thread:
                continue
            _, changed = upsert_card(
                connection=conn, source=Card.Source.GMAIL, external_id=thread_id, data=gmail_card_data(thread)
            )
            stats["upserted"] += 1
            stats["changed"] += int(changed)
    except Exception as exc:  # Google client raises many types; surface them all on /connections/
        conn.last_error = str(exc)[:1000]
        conn.save(update_fields=["last_error", "updated_at"])
        log.warning("Gmail sync failed: %s", exc)
        stats["error"] = str(exc)
        return stats
    conn.last_sync_at = timezone.now()
    conn.last_error = ""
    conn.sync_cursor = {"stats": stats}
    conn.save(update_fields=["last_sync_at", "last_error", "sync_cursor", "updated_at"])
    return stats
