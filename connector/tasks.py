import logging

from django.conf import settings
from procrastinate.contrib.django import app

from . import services

log = logging.getLogger(__name__)


@app.task(queueing_lock="sync_odoo", name="connector.sync_odoo")
def sync_odoo():
    if settings.ODOO_URL and settings.ODOO_API_KEY:
        log.info("Odoo sync: %s", services.sync_odoo())


@app.task(queueing_lock="sync_gmail", name="connector.sync_gmail")
def sync_gmail():
    log.info("Gmail sync: %s", services.sync_gmail())


@app.periodic(cron="*/5 * * * *", periodic_id="sync_odoo")
@app.task(queueing_lock="sync_odoo_periodic", name="connector.sync_odoo_periodic")
def sync_odoo_periodic(timestamp: int):
    sync_odoo()


@app.periodic(cron="*/5 * * * *", periodic_id="sync_gmail")
@app.task(queueing_lock="sync_gmail_periodic", name="connector.sync_gmail_periodic")
def sync_gmail_periodic(timestamp: int):
    from pathlib import Path

    if Path(settings.GMAIL_TOKEN_FILE).exists():
        sync_gmail()
