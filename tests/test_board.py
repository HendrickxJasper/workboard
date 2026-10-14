"""Rules 6, 13, skills indexing (11) and smoke tests for every URL."""

import subprocess
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from card import services
from card.models import Card
from skill import services as skill_services
from skill.models import SkillRepo

from . import factories as f

pytestmark = pytest.mark.django_db
HX = {"HTTP_HX_REQUEST": "true"}


# --- rule 6 ---------------------------------------------------------------------
def test_r6_running_via_agent_run():
    card = f.card()
    f.run(card, status="running")
    assert services.activity_state(card) == "running"
    assert list(Card.objects.running()) == [card]


def test_r6_running_via_timer():
    card = f.card(timer_running=True)
    assert services.activity_state(card) == "running"


def test_r6_idle_after_threshold_but_done_never_idle():
    old = timezone.now() - timedelta(days=5)
    idle = f.card(last_activity_at=old)
    done = f.card(last_activity_at=old, column="done")
    fresh = f.card()
    assert services.activity_state(idle) == "idle"
    assert services.activity_state(done) == "active"
    assert services.activity_state(fresh) == "active"
    assert list(Card.objects.idle()) == [idle]


def test_counters():
    f.card(timer_running=True)
    f.card(last_activity_at=timezone.now() - timedelta(days=9))
    assert services.counters() == {"running": 1, "idle": 1, "to_approve": 0}


# --- rule 13 --------------------------------------------------------------------
def test_r13_move_sets_column_and_order():
    a, b = f.card(column="triaged", position=0), f.card(column="triaged", position=1)
    moving = f.card(column="inbox", last_activity_at=timezone.now() - timedelta(days=9))
    services.move_card(moving, "triaged", 1)
    order = list(Card.objects.filter(column="triaged").order_by("position").values_list("pk", flat=True))
    assert order == [a.pk, moving.pk, b.pk]
    moving.refresh_from_db()
    assert services.activity_state(moving) == "active"  # moving it counts as activity


def test_move_view_rejects_unknown_column_and_rerenders_board(auth_client):
    card = f.card()
    resp = auth_client.post(reverse("card:move", args=[card.pk]), {"column": "nope", "position": 0}, **HX)
    assert resp.status_code == 200 and resp["HX-Retarget"] == "#board"
    card.refresh_from_db()
    assert card.column == "inbox"


def test_move_view_returns_counters_and_oob_face(auth_client):
    card = f.card()
    resp = auth_client.post(
        reverse("card:move", args=[card.pk]), {"column": "waiting_me", "position": 0}, **HX
    )
    body = resp.content.decode()
    assert 'id="board-counters"' in body and 'hx-swap-oob="true"' in body
    card.refresh_from_db()
    assert card.column == "waiting_me"


def test_running_card_face_polls_and_idle_does_not(auth_client):
    running = f.card()
    f.run(running, status="running", current_step="Looking up res.partner")
    idle = f.card(last_activity_at=timezone.now() - timedelta(days=9))
    run_html = auth_client.get(reverse("card:face", args=[running.pk])).content.decode()
    idle_html = auth_client.get(reverse("card:face", args=[idle.pk])).content.decode()
    assert "every 3s" in run_html and "Looking up res.partner" in run_html
    assert "every 3s" not in idle_html and "Idle 9d" in idle_html


# --- skills (rule 11) -------------------------------------------------------------
SKILL_MD = "---\nname: {name}\ndescription: {desc}\n---\n# body\n"


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def _make_skills_repo(tmp_path):
    origin = tmp_path / "origin"
    skill_dir = origin / "plugins" / "odoo-tools" / "skills" / "document-module"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SKILL_MD.format(name="document-module", desc="Document a module"))
    plain = origin / "devops" / "deploy-odoo-sh"
    plain.mkdir(parents=True)
    (plain / "SKILL.md").write_text(SKILL_MD.format(name="deploy-odoo-sh", desc="Deploy"))
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    _git(origin, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return origin


def test_skills_clone_and_index_marketplace_and_plain_layouts(tmp_path):
    origin = _make_skills_repo(tmp_path)
    repo = SkillRepo.objects.create(name="Team", remote_url=str(origin), local_path=str(tmp_path / "clone"))
    skill_services.pull_repo(repo)
    cats = dict(repo.skills.values_list("slug", "category"))
    assert cats == {"document-module": "odoo-tools", "deploy-odoo-sh": "devops"}
    assert "body" in skill_services.read_skill(repo.skills.get(slug="document-module"))


def test_r11_dirty_clone_aborts_pull(tmp_path):
    origin = _make_skills_repo(tmp_path)
    repo = SkillRepo.objects.create(name="Team", remote_url=str(origin), local_path=str(tmp_path / "clone"))
    skill_services.pull_repo(repo)
    (tmp_path / "clone" / "devops" / "deploy-odoo-sh" / "SKILL.md").write_text("local edit")
    with pytest.raises(skill_services.SkillRepoError, match="Local changes"):
        skill_services.pull_repo(repo)
    repo.refresh_from_db()
    assert "Local changes" in repo.last_error


# --- smoke tests --------------------------------------------------------------------
def test_login_required(client):
    resp = client.get(reverse("card:board"))
    assert resp.status_code == 302 and "/login/" in resp["Location"]


@pytest.mark.parametrize("name", ["card:board", "card:counters", "connector:index", "skill:index"])
def test_pages_render(auth_client, name):
    assert auth_client.get(reverse(name)).status_code == 200


def test_board_filters_render(auth_client):
    f.card(timer_running=True, title="Timer card")
    resp = auth_client.get(
        reverse("card:board") + "?state=running", HTTP_HX_REQUEST="true", HTTP_HX_TARGET="board"
    )
    assert resp.status_code == 200 and "Timer card" in resp.content.decode()
    assert "<html" not in resp.content.decode()


def test_drawer_and_face(auth_client):
    card = f.card()
    run = f.run(card, status="awaiting_approval")
    f.action(run)
    assert auth_client.get(reverse("card:detail", args=[card.pk]), **HX).status_code == 200
    assert auth_client.get(reverse("card:detail", args=[card.pk])).status_code == 302
    assert auth_client.get(reverse("card:face", args=[card.pk])).status_code == 200


def test_quick_add_creates_manual_card(auth_client):
    resp = auth_client.post(reverse("card:new"), {"title": "Write minutes"}, **HX)
    assert resp.status_code == 200 and Card.objects.filter(title="Write minutes", source="manual").exists()


def test_triage_button_queues_run(auth_client):
    card = f.card()
    auth_client.post(reverse("card:triage", args=[card.pk]), **HX)
    assert card.runs.filter(status="queued").exists()


def test_approve_and_reject_endpoints(auth_client):
    card = f.card()
    run = f.run(card, status="awaiting_approval")
    keep, drop = f.action(run, sequence=0), f.action(run, sequence=1)
    resp = auth_client.post(
        reverse("agent:approve", args=[keep.pk]), {"payload": '{"title": "Edited"}'}, **HX
    )
    assert resp.status_code == 200 and Card.objects.filter(title="Edited").exists()
    auth_client.post(reverse("agent:reject", args=[drop.pk]), **HX)
    drop.refresh_from_db()
    assert drop.status == "rejected"


def test_approve_with_bad_json_shows_error(auth_client):
    card = f.card()
    act = f.action(f.run(card, status="awaiting_approval"))
    resp = auth_client.post(reverse("agent:approve", args=[act.pk]), {"payload": "{nope"}, **HX)
    assert "not valid JSON" in resp.content.decode()


def test_approve_all_endpoint(auth_client):
    card = f.card()
    run = f.run(card, status="awaiting_approval")
    f.action(run)
    auth_client.post(reverse("agent:approve_all", args=[run.pk]), **HX)
    run.refresh_from_db()
    assert run.status == "succeeded"
