"""Agent runs and proposed actions (rules 3, 4, 5, 7, 8, 12)."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from card.models import Card, Client
from card.services import touch
from core.enqueue import enqueue

from .actions import Clients, execute, validate_payload
from .models import AgentRun, ProposedAction

log = logging.getLogger(__name__)


# --- queueing (rule 3) ---------------------------------------------------------
def active_run(card: Card) -> AgentRun | None:
    return card.runs.filter(status__in=AgentRun.ACTIVE_STATUSES).first()


def queue_run(card: Card, kind: str = AgentRun.Kind.TRIAGE) -> AgentRun:
    """Queue a run unless one is already queued or running for this card."""
    existing = active_run(card)
    if existing:
        return existing
    try:
        with transaction.atomic():
            run = AgentRun.objects.create(card=card, kind=kind, current_step="Queued")
    except IntegrityError:  # raced with another sync: the constraint kept it to one
        return active_run(card)
    from . import tasks

    enqueue(tasks.run_agent, run_id=run.pk)
    return run


def set_step(run: AgentRun, text: str):
    run.current_step = text[:200]
    AgentRun.objects.filter(pk=run.pk).update(current_step=run.current_step, updated_at=timezone.now())


def finish_run(run: AgentRun, status: str, *, error: str = ""):
    run.status = status
    run.error = error[:4000]
    run.finished_at = timezone.now()
    run.current_step = "" if status != AgentRun.Status.FAILED else "Failed"
    run.save(update_fields=["status", "error", "finished_at", "current_step", "updated_at"])


# --- executing a run -------------------------------------------------------------
def execute_run(run_id: int, *, llm=None, odoo=None):
    """Called by the worker. Claims the run, calls Claude, applies the result."""
    from skill.services import catalogue, read_skill

    from .claude import TriageError, default_llm, run_triage

    claimed = AgentRun.objects.filter(pk=run_id, status=AgentRun.Status.QUEUED).update(
        status=AgentRun.Status.RUNNING, started_at=timezone.now(), current_step="Starting"
    )
    if not claimed:
        return None  # already handled (idempotent)
    run = AgentRun.objects.select_related("card", "card__client").get(pk=run_id)
    run.model = settings.CLAUDE_MODEL
    run.save(update_fields=["model", "updated_at"])
    try:
        llm = llm or default_llm()
        if odoo is None and settings.ODOO_URL and settings.ODOO_API_KEY:
            from connector.odoo import OdooClient

            odoo = OdooClient.from_settings()
        out = run_triage(
            run.card,
            llm=llm,
            odoo=odoo,
            skills=catalogue(),
            read_skill=read_skill,
            on_step=lambda text: set_step(run, text),
        )
    except (TriageError, Exception) as exc:  # noqa: B014 - any failure ends the run visibly
        log.exception("Run %s failed", run_id)
        finish_run(run, AgentRun.Status.FAILED, error=str(exc))
        return run
    run.transcript = out["transcript"]
    run.input_tokens = out["usage"]["input_tokens"]
    run.output_tokens = out["usage"]["output_tokens"]
    run.save(update_fields=["transcript", "input_tokens", "output_tokens", "updated_at"])
    apply_triage(run, out["result"], skills_read=out["skills_read"])
    return run


# --- applying a triage result (rules 4, 8, 12) -----------------------------------
@transaction.atomic
def apply_triage(run: AgentRun, result: dict, *, skills_read=()) -> AgentRun:
    from skill.models import Skill
    from skill.services import record_usage

    card = run.card
    score = max(0, min(3, int(result.get("ai_assist_score") or 0)))
    urgency = result.get("urgency") if result.get("urgency") in Card.Urgency.values else card.urgency
    card.ai_assist_score = score
    card.urgency = urgency
    card.summary = str(result.get("summary", ""))[:2000]
    card.next_step = str(result.get("next_step", ""))[:2000]
    if not card.client_id:
        card.client = _match_client(result)

    created, dropped = [], []
    for index, item in enumerate(result.get("actions") or []):
        try:
            payload = validate_payload(item.get("type"), item.get("payload") or {})
        except ValidationError as exc:
            dropped.append({"index": index, "type": item.get("type"), "reason": "; ".join(exc.messages)})
            created.append(None)
            continue
        dep_index = item.get("depends_on")
        depends_on = None
        if isinstance(dep_index, int) and 0 <= dep_index < index:
            depends_on = created[dep_index]
        created.append(
            ProposedAction.objects.create(
                run=run,
                card=card,
                sequence=index,
                action_type=item["type"],
                title=str(item.get("title", ""))[:200],
                payload=payload,
                depends_on=depends_on,
            )
        )
    has_actions = any(created)
    if card.column == Card.Column.INBOX:
        card.column = Card.Column.AI_DRAFTED if score >= 2 and has_actions else Card.Column.TRIAGED
    card.last_activity_at = timezone.now()
    card.save()

    run.result = {**result, "dropped_actions": dropped} if dropped else result
    run.save(update_fields=["result", "updated_at"])
    slugs = set(result.get("skills_used") or []) | {s.slug for s in skills_read}
    record_usage(run, Skill.objects.filter(slug__in=slugs))
    finish_run(run, AgentRun.Status.AWAITING_APPROVAL if has_actions else AgentRun.Status.SUCCEEDED)
    return run


def _match_client(result: dict) -> Client | None:
    partner_id = result.get("odoo_partner_id")
    if isinstance(partner_id, int) and partner_id > 0:
        client, _ = Client.objects.get_or_create(
            odoo_partner_id=partner_id, defaults={"name": result.get("client_name") or f"#{partner_id}"}
        )
        return client
    name = (result.get("client_name") or "").strip()
    return Client.objects.filter(name__iexact=name).first() if name else None


# --- approving and executing actions (rule 5) -----------------------------------
def approve_action(action: ProposedAction, *, payload: dict | None = None, clients: Clients | None = None):
    if action.status == ProposedAction.Status.EXECUTED:
        return action
    if action.status == ProposedAction.Status.REJECTED:
        raise ValidationError("This action was rejected.")
    if payload is not None:
        action.payload = validate_payload(action.action_type, payload)
    if action.depends_on_id and action.depends_on.status != ProposedAction.Status.EXECUTED:
        raise ValidationError(f"Approve “{action.depends_on}” first.")
    action.status = ProposedAction.Status.APPROVED
    action.save(update_fields=["payload", "status", "updated_at"])
    return execute_action(action, clients=clients or Clients())


def execute_action(action: ProposedAction, *, clients: Clients) -> ProposedAction:
    if action.status == ProposedAction.Status.EXECUTED and action.result:
        return action  # idempotent
    try:
        action.result = execute(action, clients)
    except Exception as exc:
        action.status = ProposedAction.Status.FAILED
        action.error = str(exc)[:2000]
        action.save(update_fields=["status", "error", "updated_at"])
        raise ValidationError(f"{action}: {exc}") from exc
    action.status = ProposedAction.Status.EXECUTED
    action.error = ""
    action.executed_at = timezone.now()
    action.save(update_fields=["status", "result", "error", "executed_at", "updated_at"])
    _after_action(action)
    return action


def reject_action(action: ProposedAction) -> ProposedAction:
    if action.status == ProposedAction.Status.EXECUTED:
        raise ValidationError("Already executed.")
    action.status = ProposedAction.Status.REJECTED
    action.save(update_fields=["status", "updated_at"])
    for dependent in action.dependents.filter(status=ProposedAction.Status.PROPOSED):
        reject_action(dependent)
    _after_action(action)
    return action


def approve_all(run: AgentRun, *, clients: Clients | None = None) -> list[ProposedAction]:
    clients = clients or Clients()
    done = []
    for action in run.actions.filter(
        status__in=[ProposedAction.Status.PROPOSED, ProposedAction.Status.FAILED]
    ):
        action.refresh_from_db()
        if action.status in (ProposedAction.Status.PROPOSED, ProposedAction.Status.FAILED):
            done.append(approve_action(action, clients=clients))
    return done


def _after_action(action: ProposedAction):
    """When every action of a run is handled, the run succeeds."""
    run = action.run
    touch(action.card)
    if not run.actions.filter(status__in=ProposedAction.OPEN_STATUSES).exists():
        if run.status == AgentRun.Status.AWAITING_APPROVAL:
            finish_run(run, AgentRun.Status.SUCCEEDED)


# --- housekeeping (rule 7) -------------------------------------------------------
def reap_stale_runs() -> int:
    cutoff = timezone.now() - timedelta(minutes=settings.AGENT_RUN_TIMEOUT_MIN)
    stale = AgentRun.objects.filter(status__in=AgentRun.ACTIVE_STATUSES, updated_at__lt=cutoff)
    count = 0
    for run in stale:
        finish_run(run, AgentRun.Status.FAILED, error="Timed out: no progress within the run timeout.")
        count += 1
    return count
