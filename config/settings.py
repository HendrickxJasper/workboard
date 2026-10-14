"""Workboard settings. Everything comes from environment variables (see .env.example)."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("SECRET_KEY", default="dev-only-not-secret")
DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
# e.g. https://workboard.your-tailnet.ts.net — needed for logins and HTMX posts behind a proxy
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
# Behind kamal-proxy / Cloudflare Tunnel: trust X-Forwarded-Proto for https detection
if env.bool("BEHIND_PROXY", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = env.bool("SECURE_COOKIES", default=False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django_htmx",
    "procrastinate.contrib.django",
    "core",
    "connector",
    "card",
    "agent",
    "skill",
]

MIDDLEWARE = [
    "core.middleware.HealthCheckMiddleware",  # first: answers /healthz before host checks
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.workboard",
            ],
        },
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://postgres:postgres@localhost:5432/workboard"),
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = []
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "card:board"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en"
TIME_ZONE = env("TIME_ZONE", default="Europe/Brussels")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {"procrastinate": {"level": "WARNING"}},
}

# --- Workboard ---------------------------------------------------------------
WORKBOARD_COMPANY_NAME = env("WORKBOARD_COMPANY_NAME", default="My company")
WORKBOARD_USER_NAME = env("WORKBOARD_USER_NAME", default="")
IDLE_AFTER_DAYS = env.int("IDLE_AFTER_DAYS", default=3)
AGENT_RUN_TIMEOUT_MIN = env.int("AGENT_RUN_TIMEOUT_MIN", default=15)
AUTO_TRIAGE = env.bool("AUTO_TRIAGE", default=True)

# Odoo (JSON-2 API, Odoo 19+)
ODOO_URL = env("ODOO_URL", default="").rstrip("/")
ODOO_DB = env("ODOO_DB", default="")
ODOO_API_KEY = env("ODOO_API_KEY", default="")
ODOO_LOGIN = env("ODOO_LOGIN", default="")
_support_team = env("ODOO_SUPPORT_TEAM_ID", default="").strip()
ODOO_SUPPORT_TEAM_ID = int(_support_team) if _support_team else None  # empty in .env must not crash

# Gmail
GMAIL_CREDENTIALS_FILE = env(
    "GMAIL_CREDENTIALS_FILE", default=str(BASE_DIR / "secrets" / "gmail_client.json")
)
GMAIL_TOKEN_FILE = env("GMAIL_TOKEN_FILE", default=str(BASE_DIR / "secrets" / "gmail_token.json"))
GMAIL_QUERY = env("GMAIL_QUERY", default="in:inbox -category:promotions -category:social newer_than:14d")
GMAIL_MAX_THREADS = env.int("GMAIL_MAX_THREADS", default=50)
# On a server: the token JSON from `gmail_auth --print`, written to GMAIL_TOKEN_FILE on first use
GMAIL_TOKEN_JSON = env("GMAIL_TOKEN_JSON", default="")

# Claude
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
CLAUDE_MODEL = env("CLAUDE_MODEL", default="claude-sonnet-5-5")
CLAUDE_MAX_TURNS = env.int("CLAUDE_MAX_TURNS", default=8)

# Skills repo (Claude Code plugin marketplace layout or plain folders with SKILL.md)
SKILLS_REPO_NAME = env("SKILLS_REPO_NAME", default="Team skills")
SKILLS_REPO_URL = env("SKILLS_REPO_URL", default="")
SKILLS_REPO_PATH = env("SKILLS_REPO_PATH", default=str(BASE_DIR / "var" / "skills"))
# Read-only token (e.g. GitHub fine-grained PAT) for a private skills repo over HTTPS.
# Sent as an auth header per git call; never stored in the URL or the database.
SKILLS_REPO_TOKEN = env("SKILLS_REPO_TOKEN", default="")
SKILLS_REPO_BRANCH = env("SKILLS_REPO_BRANCH", default="")  # empty = remote default
