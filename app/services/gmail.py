from __future__ import annotations

import base64
from email.message import EmailMessage
from html import unescape
import re

from googleapiclient.discovery import build

from app.config import get_settings
from app.services.google_auth import get_google_credentials


class GmailService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = build("gmail", "v1", credentials=get_google_credentials())

    def send_email(self, subject: str, body: str, to_email: str | None = None) -> None:
        sender = self.settings.gmail_sender_email
        recipient = to_email or self.settings.daily_summary_to_email
        if not sender or not recipient:
            raise RuntimeError("缺少 GMAIL_SENDER_EMAIL 或 DAILY_SUMMARY_TO_EMAIL。")

        message = EmailMessage()
        message["To"] = recipient
        message["From"] = sender
        message["Subject"] = subject
        message.set_content(body)

        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        self.client.users().messages().send(userId="me", body={"raw": encoded}).execute()

    def search_messages(self, query: str, max_results: int = 10) -> list[dict]:
        response = (
            self.client.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return response.get("messages", [])

    def get_message_text(self, message_id: str) -> dict[str, str]:
        message = (
            self.client.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        headers = {
            header["name"].lower(): header["value"]
            for header in message.get("payload", {}).get("headers", [])
        }
        text = _payload_text(message.get("payload", {}))
        return {
            "message_id": message_id,
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "date": headers.get("date", ""),
            "snippet": message.get("snippet", ""),
            "body": text[:12000],
        }


def _payload_text(payload: dict) -> str:
    parts = payload.get("parts", [])
    if parts:
        return "\n".join(_payload_text(part) for part in parts).strip()

    data = payload.get("body", {}).get("data")
    if not data:
        return ""
    decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
        "utf-8", errors="ignore"
    )
    if payload.get("mimeType") == "text/html":
        decoded = re.sub(r"<(br|/p|/div|/li|/tr|/td|/th)[^>]*>", "\n", decoded, flags=re.I)
        decoded = re.sub(r"<(p|div|li|tr|td|th|a)[^>]*>", "\n", decoded, flags=re.I)
        decoded = re.sub(r"<[^>]+>", " ", decoded)
    decoded = unescape(re.sub(r"[ \t]+", " ", decoded))
    decoded = re.sub(r"\n{3,}", "\n\n", decoded)
    return decoded.strip()
