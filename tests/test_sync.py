"""Rules 1, 2, 3 and the Odoo JSON-2 client."""

import json

import httpx
import pytest

from agent.models import AgentRun
from card.models import Card
from connector import services
from connector.odoo import OdooClient, OdooError

from . import factories as f

pytestmark = pytest.mark.django_db

ME = {"res.users": [{"id": 7}]}


def task(id_, name="Task", **kw):
    return {
        "id": id_,
        "name": name,
        "description": "<p>Do it</p>",
        "partner_id": [42, "Acme"],
        "project_id": [1, "Impl"],
        "stage_id": [3, "Doing"],
        "date_deadline": False,
        "priority": "0",
        **kw,
    }


def test_r1_upsert_twice_gives_one_card_and_change_bumps_activity():
    conn = f.connection()
    card, changed = services.upsert_card(
        connection=conn, source="odoo_task", external_id="1", data={"title": "A"}
    )
    first_activity = card.last_activity_at
    card2, changed2 = services.upsert_card(
        connection=conn, source="odoo_task", external_id="1", data={"title": "A"}
    )
    assert card2.pk == card.pk and changed and not changed2
    assert Card.objects.count() == 1
    card3, changed3 = services.upsert_card(
        connection=conn, source="odoo_task", external_id="1", data={"title": "B"}
    )
    assert changed3 and card3.last_activity_at > first_activity


def test_r1_odoo_sync_maps_tasks_and_clients():
    odoo = f.FakeOdoo({**ME, "project.task": [task(10, "Build report", priority="1")]})
    stats = services.sync_odoo(odoo)
    card = Card.objects.get(source="odoo_task", external_id="10")
    assert stats["upserted"] == 1
    assert card.title == "Build report" and card.urgency == "high"
    assert card.client.odoo_partner_id == 42 and card.excerpt == "Do it"
    assert card.external_url == "https://odoo.test/odoo/project.task/10"


def test_r2_task_that_left_my_open_list_moves_to_done():
    services.sync_odoo(f.FakeOdoo({**ME, "project.task": [task(10), task(11)]}))
    services.sync_odoo(f.FakeOdoo({**ME, "project.task": [task(11)]}))
    assert Card.objects.get(external_id="10").column == "done"
    assert Card.objects.get(external_id="11").column != "done"


def test_r2_gmail_card_is_never_auto_closed():
    gmail = f.FakeGmail({"t1": f.thread("t1")})
    services.sync_gmail(gmail)
    services.sync_gmail(f.FakeGmail({}))
    assert Card.objects.get(source="gmail").column == "inbox"


def test_r2_new_mail_reopens_done_thread():
    services.sync_gmail(f.FakeGmail({"t1": f.thread("t1", snippet="first")}))
    Card.objects.update(column="done")
    services.sync_gmail(f.FakeGmail({"t1": f.thread("t1", snippet="second")}))
    assert Card.objects.get(source="gmail").column == "inbox"


def test_r3_triage_queued_once_per_content_change():
    services.sync_gmail(f.FakeGmail({"t1": f.thread("t1")}))
    card = Card.objects.get()
    assert AgentRun.objects.filter(card=card).count() == 1
    AgentRun.objects.update(status="succeeded")
    services.sync_gmail(f.FakeGmail({"t1": f.thread("t1")}))
    assert AgentRun.objects.filter(card=card).count() == 1  # unchanged hash: no new run


def test_gmail_client_matched_by_domain():
    acme = f.client(name="Acme", email_domains=["acme.test"])
    services.sync_gmail(f.FakeGmail({"t1": f.thread("t1", from_email="tom@acme.test")}))
    assert Card.objects.get().client == acme


def test_odoo_timer_marks_card_running():
    odoo = f.FakeOdoo(
        {**ME, "project.task": [task(10)], "timer.timer": [{"res_model": "project.task", "res_id": 10}]}
    )
    services.sync_odoo(odoo)
    assert Card.objects.get(external_id="10").timer_running


def test_missing_app_is_skipped_not_closed():
    class NoHelpdesk(f.FakeOdoo):
        def search_read(self, model, *a, **kw):
            if model == "helpdesk.ticket":
                raise OdooError("Model helpdesk.ticket does not exist", status=404)
            return super().search_read(model, *a, **kw)

    f.card(source="odoo_ticket", external_id="5", column="triaged")
    stats = services.sync_odoo(NoHelpdesk(ME))
    assert "helpdesk.ticket" in stats["skipped"]
    assert Card.objects.get(external_id="5").column == "triaged"


def test_odoo_client_json2_request_format():
    seen = {}

    def handler(request):
        seen.update(
            path=request.url.path,
            auth=request.headers["Authorization"],
            db=request.headers["X-Odoo-Database"],
            body=json.loads(request.content),
        )
        return httpx.Response(200, json=[17])

    odoo = OdooClient("https://o.test", "prod", "KEY", transport=httpx.MockTransport(handler))
    assert odoo.create("helpdesk.ticket", {"name": "X"}) == 17
    assert seen == {
        "path": "/json/2/helpdesk.ticket/create",
        "auth": "bearer KEY",
        "db": "prod",
        "body": {"vals_list": [{"name": "X"}]},
    }


def test_odoo_client_raises_on_error_status():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(403, json={"name": "AccessError", "message": "Nope"})
    )
    odoo = OdooClient("https://o.test", "prod", "KEY", transport=transport)
    with pytest.raises(OdooError, match="Nope"):
        odoo.search_read("res.partner", [], ["name"])
