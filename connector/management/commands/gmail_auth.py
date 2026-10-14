from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from connector.gmail import SCOPES


class Command(BaseCommand):
    help = (
        "One-time Gmail OAuth consent. Prints a Google URL; after you approve, Google redirects to "
        "http://localhost:<port>/ and the token is stored in GMAIL_TOKEN_FILE."
    )

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=8085, help="Local callback port (default 8085).")
        parser.add_argument(
            "--bind", default="127.0.0.1", help="Address to listen on; 0.0.0.0 inside a container."
        )
        parser.add_argument("--no-browser", action="store_true", help="Only print the URL.")
        parser.add_argument(
            "--print",
            action="store_true",
            dest="print_token",
            help="Also print the token JSON, to store as the GMAIL_TOKEN_JSON secret on a server.",
        )

    def handle(self, *args, port, bind, no_browser, print_token, **options):
        from google_auth_oauthlib.flow import InstalledAppFlow

        secrets = Path(settings.GMAIL_CREDENTIALS_FILE)
        if not secrets.exists():
            raise CommandError(
                f"{secrets} not found. In Google Cloud console: enable the Gmail API, create an OAuth "
                "client of type 'Desktop app', and save its JSON as secrets/gmail_client.json."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
        creds = flow.run_local_server(
            host="localhost",
            bind_addr=bind,
            port=port,
            open_browser=not no_browser,
            authorization_prompt_message="Open this URL in your browser and approve access:\n\n{url}\n",
        )
        token = Path(settings.GMAIL_TOKEN_FILE)
        token.parent.mkdir(parents=True, exist_ok=True)
        token.write_text(creds.to_json())
        self.stdout.write(self.style.SUCCESS(f"Saved Gmail token to {token}"))
        if print_token:
            self.stdout.write(
                "\nGMAIL_TOKEN_JSON (secret: it grants access to your mailbox):\n" + creds.to_json()
            )
