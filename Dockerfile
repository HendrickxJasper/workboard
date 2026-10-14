# One image for both roles: web (gunicorn, the default CMD) and worker (procrastinate).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git: cloning/pulling the skills repo
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

WORKDIR /app
COPY requirements.lock .
RUN pip install -r requirements.lock

COPY --chown=app:app . .
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && mkdir -p /app/data \
    && chown -R app:app /app/data /app/staticfiles \
    && chmod +x /app/bin/docker-entrypoint

# Persistent state (Gmail token, skills clone) lives in /app/data: mount a volume there.
ENV DEBUG=false \
    GMAIL_TOKEN_FILE=/app/data/gmail_token.json \
    GMAIL_CREDENTIALS_FILE=/app/secrets/gmail_client.json \
    SKILLS_REPO_PATH=/app/data/skills

USER app
EXPOSE 8000
ENTRYPOINT ["/app/bin/docker-entrypoint"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--access-logfile", "-"]
