"""Server/container concerns: health check, Gmail token bootstrap, skills repo auth."""

import base64
import json

import pytest

from connector.gmail import gmail_configured
from skill import services as skill_services
from skill.models import SkillRepo


@pytest.mark.django_db
def test_healthz_ok_without_login_and_for_unknown_hosts(client):
    resp = client.get("/healthz", HTTP_HOST="10.0.0.7:8000")  # kamal-proxy probes the container IP
    assert resp.status_code == 200 and resp.content == b"ok"


def test_healthz_reports_database_down(client, monkeypatch):
    def broken_cursor():
        raise RuntimeError("db down")

    monkeypatch.setattr("core.middleware.connection.cursor", broken_cursor)
    assert client.get("/healthz").status_code == 503


def test_gmail_token_seeded_from_env_once(settings, tmp_path):
    token = tmp_path / "data" / "gmail_token.json"
    settings.GMAIL_TOKEN_FILE = str(token)
    settings.GMAIL_TOKEN_JSON = ""
    assert not gmail_configured()
    settings.GMAIL_TOKEN_JSON = json.dumps({"refresh_token": "r1"})
    assert gmail_configured() and json.loads(token.read_text()) == {"refresh_token": "r1"}
    token.write_text(json.dumps({"refresh_token": "refreshed"}))
    settings.GMAIL_TOKEN_JSON = json.dumps({"refresh_token": "stale"})
    gmail_configured()
    assert json.loads(token.read_text()) == {"refresh_token": "refreshed"}  # the file wins


@pytest.mark.django_db
def test_skills_token_goes_in_a_header_not_the_url(settings, tmp_path, monkeypatch):
    settings.SKILLS_REPO_TOKEN = "ghp_secret"
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "abc123", ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs["env"]))
        if "clone" in cmd:
            (tmp_path / "clone" / ".git").mkdir(parents=True)
        return Done()

    monkeypatch.setattr("skill.services.subprocess.run", fake_run)
    repo = SkillRepo.objects.create(
        name="Team", remote_url="https://github.com/acme/skills", local_path=str(tmp_path / "clone")
    )
    skill_services.pull_repo(repo)
    clone_cmd, env = calls[0]
    expected = base64.b64encode(b"x-access-token:ghp_secret").decode()
    assert f"http.extraHeader=Authorization: Basic {expected}" in clone_cmd
    assert "https://github.com/acme/skills" in clone_cmd and env["GIT_TERMINAL_PROMPT"] == "0"
    repo.refresh_from_db()
    assert "ghp_secret" not in repo.remote_url
