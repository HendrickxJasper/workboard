"""Rules 4, 5, 7, 8, 12: triage, approvals and housekeeping."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from agent import services
from agent.actions import Clients
from agent.models import AgentRun, ProposedAction
from card.models import Card

from . import factories as f

pytestmark = pytest.mark.django_db


def triage_result(score=3, actions=None, **kw):
    return {
        "classification": "support_request",
        "summary": "S",
        "urgency": "high",
        "ai_assist_score": score,
        "next_step": "Approve",
        "actions": actions or [],
        "skills_used": [],
        **kw,
    }


SUPPORT_ACTIONS = [
    {
        "type": "odoo_create_ticket",
        "title": "Ticket",
        "payload": {"name": "Lot error", "description": "Fails", "partner_id": 42},
    },
    {
        "type": "odoo_post_note",
        "title": "Analysis",
        "depends_on": 0,
        "payload": {"res_id": None, "body": "Cause and fix"},
    },
    {
        "type": "gmail_create_draft",
        "title": "Reply",
        "depends_on": 0,
        "payload": {
            "thread_id": "t1",
            "to": "tom@acme.test",
            "subject": "Re: Help",
            "body": "Support has ticket {depends_on_id}.",
        },
    },
]


def test_r4_high_score_with_actions_goes_to_ai_drafted():
    card = f.card(source="gmail")
    run = f.run(card, status="running")
    services.apply_triage(run, triage_result(3, SUPPORT_ACTIONS))
    card.refresh_from_db()
    run.refresh_from_db()
    assert card.column == "ai_drafted" and card.ai_assist_score == 3 and card.urgency == "high"
    assert run.status == "awaiting_approval" and run.actions.count() == 3


def test_r4_score_zero_goes_to_triaged_without_actions():
    card = f.card(source="gmail")
    run = f.run(card, status="running")
    services.apply_triage(run, triage_result(0))
    card.refresh_from_db()
    run.refresh_from_db()
    assert card.column == "triaged" and run.status == "succeeded" and not run.actions.exists()


def test_invalid_action_payload_is_dropped_not_fatal():
    card = f.card(source="gmail")
    run = f.run(card, status="running")
    services.apply_triage(
        run, triage_result(3, [{"type": "gmail_create_draft", "title": "x", "payload": {}}])
    )
    run.refresh_from_db()
    assert not run.actions.exists() and run.result["dropped_actions"]


def test_r5_nothing_executes_without_approval_and_execution_is_idempotent():
    card = f.card(source="gmail")
    run = f.run(card, status="running")
    services.apply_triage(run, triage_result(3, SUPPORT_ACTIONS))
    odoo, gmail = f.FakeOdoo(), f.FakeGmail()
    assert odoo.calls == [] and gmail.drafts == []
    ticket = run.actions.get(sequence=0)
    clients = Clients(odoo=odoo, gmail=gmail)
    services.approve_action(ticket, clients=clients)
    services.approve_action(ticket, clients=clients)
    assert [c[0] for c in odoo.calls] == ["create"]


def test_r5_dependent_action_waits_for_its_parent():
    card = f.card(source="gmail")
    run = f.run(card, status="running")
    services.apply_triage(run, triage_result(3, SUPPORT_ACTIONS))
    note = run.actions.get(sequence=1)
    with pytest.raises(ValidationError):
        services.approve_action(note, clients=Clients(odoo=f.FakeOdoo()))


def test_r8_support_mail_end_to_end(settings):
    settings.ODOO_SUPPORT_TEAM_ID = 3
    card = f.card(source="gmail", raw={"from_email": "tom@acme.test", "body": "Validation fails"})
    run = services.queue_run(card)
    llm = f.FakeLLM(
        [
            f.tool_use(
                "odoo_search_read", {"model": "res.partner", "domain": [["email", "=ilike", "%@acme.test"]]}
            ),
            f.tool_use(
                "submit_triage",
                triage_result(3, SUPPORT_ACTIONS, odoo_partner_id=42, client_name="Acme"),
                tool_id="tu_2",
            ),
        ]
    )
    odoo = f.FakeOdoo({"res.partner": [{"id": 42, "name": "Acme"}]})
    services.execute_run(run.pk, llm=llm, odoo=odoo)
    run.refresh_from_db()
    card.refresh_from_db()
    assert run.status == "awaiting_approval" and run.input_tokens == 200
    assert card.client.odoo_partner_id == 42 and card.column == "ai_drafted"
    # second call carried the tool result back to Claude
    assert llm.calls[1]["messages"][2]["content"][0]["type"] == "tool_result"

    gmail = f.FakeGmail()
    services.approve_all(run, clients=Clients(odoo=odoo, gmail=gmail))
    creates = [c for c in odoo.calls if c[0] == "create"]
    notes = [c for c in odoo.calls if c[0] == "message_post"]
    assert creates[0][2]["team_id"] == 3 and creates[0][2]["partner_id"] == 42
    assert notes[0][1:3] == ("helpdesk.ticket", 501)
    assert gmail.drafts[0]["body"] == "Support has ticket 501."
    run.refresh_from_db()
    assert run.status == "succeeded"
    assert set(run.actions.values_list("status", flat=True)) == {"executed"}


def test_reject_cascades_to_dependents_and_finishes_run():
    card = f.card(source="gmail")
    run = f.run(card, status="running")
    services.apply_triage(run, triage_result(3, SUPPORT_ACTIONS))
    services.reject_action(run.actions.get(sequence=0))
    run.refresh_from_db()
    assert set(run.actions.values_list("status", flat=True)) == {"rejected"}
    assert run.status == "succeeded"


def test_claude_without_submit_fails_the_run():
    card = f.card()
    run = services.queue_run(card)
    text = {"content": [{"type": "text", "text": "Hmm"}], "usage": {"input_tokens": 1, "output_tokens": 1}}
    services.execute_run(run.pk, llm=f.FakeLLM([text, text]), odoo=None)
    run.refresh_from_db()
    assert run.status == "failed" and "without submitting" in run.error


def test_queue_run_keeps_one_active_run_per_card():
    card = f.card()
    assert services.queue_run(card).pk == services.queue_run(card).pk
    assert AgentRun.objects.count() == 1


def test_execute_run_is_idempotent():
    card = f.card()
    run = f.run(card, status="succeeded")
    assert services.execute_run(run.pk, llm=f.FakeLLM([])) is None


def test_r7_stale_running_run_is_reaped():
    card = f.card()
    run = f.run(card, status="running")
    AgentRun.objects.filter(pk=run.pk).update(updated_at=timezone.now() - timedelta(minutes=30))
    assert services.reap_stale_runs() == 1
    run.refresh_from_db()
    assert run.status == "failed"


def test_r12_skills_used_increment_usage():
    sk = f.skill(slug="support-triage")
    card = f.card(source="gmail")
    run = f.run(card, status="running")
    services.apply_triage(run, triage_result(1, skills_used=["support-triage"]))
    sk.refresh_from_db()
    assert sk.usage_count == 1 and list(run.skills_used.all()) == [sk]


def test_read_skill_tool_loads_skill(monkeypatch):
    sk = f.skill(slug="odoo-support", description="How we handle support")
    monkeypatch.setattr("skill.services.read_skill", lambda s: "# Support skill")
    card = f.card()
    run = services.queue_run(card)
    llm = f.FakeLLM(
        [
            f.tool_use("read_skill", {"slug": "odoo-support"}),
            f.tool_use("submit_triage", triage_result(1), tool_id="tu_2"),
        ]
    )
    services.execute_run(run.pk, llm=llm, odoo=None)
    sk.refresh_from_db()
    assert sk.usage_count == 1
    assert "odoo-support" in llm.calls[0]["messages"][0]["content"]  # catalogue in the prompt


def test_create_todo_action_creates_card():
    card = f.card()
    run = f.run(card, status="awaiting_approval")
    act = f.action(run, payload={"title": "Call Tom", "due_date": "2026-10-20"})
    services.approve_action(act, clients=Clients())
    todo = Card.objects.get(title="Call Tom")
    assert todo.column == "waiting_me" and str(todo.due_date) == "2026-10-20"
    assert ProposedAction.objects.get(pk=act.pk).result == {"card_id": todo.pk}
