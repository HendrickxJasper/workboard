from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from connector import services
from skill import services as skill_services


class Command(BaseCommand):
    help = "Run Odoo, Gmail and skills sync once in the foreground (handy for debugging)."

    def handle(self, *args, **options):
        if settings.ODOO_URL and settings.ODOO_API_KEY:
            self.stdout.write(f"Odoo:   {services.sync_odoo()}")
        else:
            self.stdout.write("Odoo:   not configured")
        if Path(settings.GMAIL_TOKEN_FILE).exists():
            self.stdout.write(f"Gmail:  {services.sync_gmail()}")
        else:
            self.stdout.write("Gmail:  not authorised (make gmail-auth)")
        repo = skill_services.ensure_repo_from_settings()
        if repo:
            try:
                skill_services.pull_repo(repo)
                self.stdout.write(f"Skills: {repo.skills.count()} indexed from {repo}")
            except skill_services.SkillRepoError as exc:
                self.stdout.write(f"Skills: {exc}")
        else:
            self.stdout.write("Skills: not configured")
