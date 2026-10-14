from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from agent.models import AgentRun, ProposedAction
from card.models import Card, Client


class Command(BaseCommand):
    help = (
        "Fill the board with fictional demo cards (no credentials needed). Use --reset to wipe cards first."
    )

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args, reset=False, **options):
        if reset:
            Card.objects.all().delete()
            Client.objects.all().delete()
        now = timezone.now()
        acme = Client.objects.create(
            name="Acme Cycling", odoo_partner_id=9001, email_domains=["acme-cycling.test"]
        )
        north = Client.objects.create(
            name="Northwind Joinery", odoo_partner_id=9002, email_domains=["northwind.test"]
        )
        harbor = Client.objects.create(
            name="Blue Harbor Logistics", odoo_partner_id=9003, email_domains=["blueharbor.test"]
        )

        def card(**kw):
            kw.setdefault("last_activity_at", now)
            return Card.objects.create(**kw)

        # Inbox: a fresh mail Claude is working on right now
        c1 = card(
            source="gmail",
            external_id="demo-1",
            title="Invoice PDF export broken since Monday",
            client=harbor,
            excerpt="From Lotte Peeters: since the update on Monday the invoice PDF comes out empty…",
            raw={
                "from_email": "lotte@blueharbor.test",
                "body": "Hi,\n\nSince the update on Monday the invoice PDF comes out empty when we print from the list view. Single invoices work.\n\nCan you have a look?\n\nLotte",
            },
        )
        AgentRun.objects.create(
            card=c1,
            kind="triage",
            status="running",
            started_at=now,
            current_step="Looking up res.partner in Odoo",
        )
        card(source="manual", title="Prepare demo data for Thursday workshop", column="inbox", position=1)

        # AI drafted: the misrouted support mail, ready for approval
        c2 = card(
            source="gmail",
            external_id="demo-2",
            column="ai_drafted",
            client=acme,
            urgency="high",
            ai_assist_score=3,
            title="Error when validating delivery for backorders",
            excerpt="From Tom Janssens: when we validate a partial delivery we get a ValidationError…",
            summary="Customer support question sent to you directly: validating partial deliveries raises a ValidationError on lot numbers.",
            next_step="Approve the support ticket, analysis note and reply draft.",
            raw={
                "from_email": "tom@acme-cycling.test",
                "thread_id": "demo-2",
                "body": "Hello,\n\nWhen we validate a partial delivery (backorder) we get: 'You need to supply a Lot/Serial number for product X'. The lots are filled in on the first move.\n\nThanks, Tom",
            },
        )
        run = AgentRun.objects.create(
            card=c2,
            kind="triage",
            status="awaiting_approval",
            started_at=now,
            finished_at=now,
            model="claude-sonnet-5-5",
            input_tokens=5210,
            output_tokens=842,
        )
        t = ProposedAction.objects.create(
            run=run,
            card=c2,
            sequence=0,
            action_type="odoo_create_ticket",
            title="Ticket for Acme Cycling: lot error on backorder validation",
            payload={
                "name": "Lot/Serial error when validating backorder",
                "partner_id": 9001,
                "priority": "2",
                "description": "Validating a partial delivery fails with 'You need to supply a Lot/Serial number'. Lots are set on the original move.",
            },
        )
        ProposedAction.objects.create(
            run=run,
            card=c2,
            sequence=1,
            action_type="odoo_post_note",
            depends_on=t,
            title="Analysis and proposed fix",
            payload={
                "model": "helpdesk.ticket",
                "res_id": None,
                "body": "Likely cause: the backorder's move lines lose lot_id when quantities are split. Check stock.move.line on the backorder; reproduce on a copy DB; fix by assigning lots before validation or patching the split.",
            },
        )
        ProposedAction.objects.create(
            run=run,
            card=c2,
            sequence=2,
            action_type="gmail_create_draft",
            depends_on=t,
            title="Reply: support has it",
            payload={
                "thread_id": "demo-2",
                "to": "tom@acme-cycling.test",
                "subject": "Re: Error when validating delivery for backorders",
                "body": "Hi Tom,\n\nThanks for reporting this. Our support team picked it up as ticket {depends_on_id}; a colleague will contact you shortly.\n\nKind regards",
            },
        )

        # Triaged
        card(
            source="odoo_task",
            external_id="demo-3",
            column="triaged",
            client=north,
            ai_assist_score=1,
            title="Configure intercompany rules for the second entity",
            next_step="Plan a 1h session with Northwind's accountant to confirm the flows.",
            due_date=date.today() + timedelta(days=5),
        )

        # Waiting on me: one with an Odoo timer running, one activity due tomorrow
        card(
            source="odoo_task",
            external_id="demo-4",
            column="waiting_me",
            client=acme,
            timer_running=True,
            title="Custom report: production lead times per sport",
            ai_assist_score=2,
            next_step="Finish the QWeb layout and test with last month's MOs.",
        )
        card(
            source="odoo_activity",
            external_id="demo-5",
            column="waiting_me",
            client=north,
            title="Call back about go-live date",
            due_date=date.today() + timedelta(days=1),
        )

        # Waiting on others: gone quiet
        card(
            source="odoo_ticket",
            external_id="demo-6",
            column="waiting_others",
            client=harbor,
            ai_assist_score=1,
            title="Waiting for customer test feedback on route planning",
            next_step="Send a friendly reminder if nothing by Friday.",
            last_activity_at=now - timedelta(days=6),
        )
        card(
            source="manual",
            title="Review Elena's module before merge",
            column="waiting_others",
            last_activity_at=now - timedelta(days=4),
        )

        # Done
        card(
            source="gmail",
            external_id="demo-7",
            column="done",
            client=acme,
            title="Price list question",
            ai_assist_score=3,
        )
        card(
            source="odoo_task",
            external_id="demo-8",
            column="done",
            client=north,
            title="Import opening balances",
        )

        if not get_user_model().objects.exists():
            get_user_model().objects.create_superuser("admin", "", "admin")
            self.stdout.write("Created user admin / admin")
        self.stdout.write(self.style.SUCCESS(f"Seeded {Card.objects.count()} cards."))
