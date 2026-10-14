"""Thin Gmail wrapper. Scopes: read mail and create drafts (never send in v1)."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

from django.conf import settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
MAX_BODY_CHARS = 8000


class GmailError(Exception):
    pass


def _header(headers, name):
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode() + b"==").decode("utf-8", errors="replace")


def _plain_text(payload) -> str:
    """Depth-first search for the first text/plain part."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        text = _plain_text(part)
        if text:
            return text
    return ""


def parse_thread(thread: dict) -> dict:
    """Reduce a Gmail thread resource to the fields a card needs."""
    messages = thread.get("messages", [])
    if not messages:
        return {}
    first, last = messages[0], messages[-1]
    fh, lh = first["payload"].get("headers", []), last["payload"].get("headers", [])
    sender_name, sender_email = parseaddr(_header(lh, "From"))
    body = _plain_text(last["payload"]) or last.get("snippet", "")
    return {
        "thread_id": thread["id"],
        "subject": _header(fh, "Subject") or "(no subject)",
        "from_name": sender_name,
        "from_email": sender_email.lower(),
        "to": _header(lh, "To"),
        "message_id": _header(lh, "Message-ID"),
        "date": _header(lh, "Date"),
        "message_count": len(messages),
        "snippet": last.get("snippet", ""),
        "body": body[:MAX_BODY_CHARS],
        "history_id": thread.get("historyId", ""),
    }


class GmailClient:
    def __init__(self, service):
        self.service = service

    @classmethod
    def from_settings(cls) -> GmailClient:
        token = Path(settings.GMAIL_TOKEN_FILE)
        if not token.exists():
            raise GmailError("Gmail is not authorised yet. Run `make gmail-auth`.")
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token.write_text(creds.to_json())
        return cls(build("gmail", "v1", credentials=creds, cache_discovery=False))

    def list_thread_ids(self, query: str, max_results: int) -> list[str]:
        resp = self.service.users().threads().list(userId="me", q=query, maxResults=max_results).execute()
        return [t["id"] for t in resp.get("threads", [])]

    def get_thread(self, thread_id: str) -> dict:
        thread = self.service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        return parse_thread(thread)

    def create_draft(
        self, *, thread_id: str, to: str, subject: str, body: str, in_reply_to: str = ""
    ) -> dict:
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft = (
            self.service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw, "threadId": thread_id}})
            .execute()
        )
        return {
            "draft_id": draft["id"],
            "url": f"https://mail.google.com/mail/u/0/#drafts?compose={draft['id']}",
        }


def thread_url(thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{thread_id}"
