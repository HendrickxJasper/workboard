import pytest


@pytest.fixture(autouse=True)
def _settings(settings, tmp_path):
    settings.AUTO_TRIAGE = True
    settings.IDLE_AFTER_DAYS = 3
    settings.AGENT_RUN_TIMEOUT_MIN = 15
    settings.ODOO_LOGIN = "me@company.test"
    settings.ODOO_SUPPORT_TEAM_ID = None
    settings.CLAUDE_MAX_TURNS = 5
    settings.SKILLS_REPO_URL = ""
    settings.SKILLS_REPO_PATH = str(tmp_path / "no-skills")
    return settings


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("me", password="pw")


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client
