from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from connector.gmail import SCOPES


class Command(BaseCommand):
    help = "One-time Gmail OAuth consent. Opens a browser and stores the token in GMAIL_TOKEN_FILE."

    def handle(self, *args, **options):
        from google_auth_oauthlib.flow import InstalledAppFlow

        secrets = Path(settings.GMAIL_CREDENTIALS_FILE)
        if not secrets.exists():
            raise CommandError(
                f"{secrets} not found. Create an OAuth client of type 'Desktop app' in Google Cloud "
                "console (Gmail API enabled) and download its JSON there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
        creds = flow.run_local_server(port=0)
        token = Path(settings.GMAIL_TOKEN_FILE)
        token.parent.mkdir(parents=True, exist_ok=True)
        token.write_text(creds.to_json())
        self.stdout.write(self.style.SUCCESS(f"Saved Gmail token to {token}"))
