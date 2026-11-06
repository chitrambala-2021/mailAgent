"""Gmail / Google Workspace provider (Gmail API, read-only OAuth)."""
from __future__ import annotations

import base64
import html
import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parseaddr

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ..config_loader import resolve_path
from .base import AuthRequiredError, Email, MailProvider

log = logging.getLogger(__name__)

READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
ALWAYS_EXCLUDED = "-in:spam -in:trash -in:sent -in:drafts"
SPAM_NAMES = {"spam", "junk", "junk email"}


class GmailProvider(MailProvider):
    name = "gmail"

    def __init__(self, email: str, settings: dict):
        super().__init__(email, settings)
        cfg = settings.get("gmail", {})
        self.credentials_file = resolve_path(cfg.get("credentials_file", "config/gmail_credentials.json"))
        self.token_dir = resolve_path(cfg.get("token_dir", "data/tokens/gmail"))
        self.scopes = cfg.get("scopes") or [READONLY_SCOPE]
        self.exclude_folders = settings.get("filters", {}).get("exclude_folders", []) or []
        self._service = None

    @property
    def token_file(self):
        return self.token_dir / f"{self.safe_id}.json"

    # ---------- auth ----------
    def authenticate(self, interactive: bool = True) -> None:
        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), self.scopes)

        if creds and not creds.valid and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                log.warning("[%s] Gmail token refresh failed; new login needed", self.email)
                creds = None

        if not creds or not creds.valid:
            if not interactive:
                raise AuthRequiredError(
                    f"[{self.email}] Gmail login required. Run: python -m src.main --login"
                )
            if not self.credentials_file.exists():
                raise AuthRequiredError(
                    f"Gmail OAuth client file not found: {self.credentials_file}. See README (Gmail setup)."
                )
            print(f"\n[{self.email}] Opening browser for Google sign-in...\n", flush=True)
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), self.scopes)
            creds = flow.run_local_server(port=0, login_hint=self.email, prompt="consent")

        self._save_token(creds)
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        profile = self._service.users().getProfile(userId="me").execute()
        signed_in = profile.get("emailAddress", "").lower()
        if signed_in and signed_in != self.email.lower():
            log.warning("[%s] Signed in as %s - notifications will be for that mailbox",
                        self.email, signed_in)

    def _save_token(self, creds: Credentials) -> None:
        self.token_dir.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(creds.to_json(), encoding="utf-8")
        os.chmod(self.token_file, 0o600)

    # ---------- fetch ----------
    def fetch_new(self, since: datetime, limit: int, unread_only: bool = True) -> list[Email]:
        if self._service is None:
            self.authenticate(interactive=False)

        query = f"after:{int(since.timestamp())} {ALWAYS_EXCLUDED}"
        if unread_only:
            query += " is:unread"
        for name in self.exclude_folders:
            if name.strip().lower() not in SPAM_NAMES:
                query += f" -label:{name.strip().replace(' ', '-')}"

        ids: list[str] = []
        page_token = None
        while len(ids) < limit:
            resp = self._service.users().messages().list(
                userId="me", q=query, maxResults=min(100, limit - len(ids)), pageToken=page_token
            ).execute()
            ids.extend(m["id"] for m in resp.get("messages", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return [self._get_email(msg_id) for msg_id in ids[:limit]]

    def _get_email(self, msg_id: str) -> Email:
        msg = self._service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

        sender_name, sender_email = parseaddr(headers.get("from", ""))
        received = datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000, tz=timezone.utc)

        return Email(
            id=msg["id"],
            account=self.email,
            provider=self.name,
            subject=headers.get("subject", "(no subject)") or "(no subject)",
            sender_email=sender_email.lower(),
            sender_name=sender_name,
            received_at=received,
            snippet=html.unescape(msg.get("snippet", "")),
            body=_extract_text(payload),
            importance=_importance(headers),
            web_link=f"https://mail.google.com/mail/?authuser={self.email}#all/{msg.get('threadId', msg['id'])}",
        )


def _importance(headers: dict) -> str:
    imp = headers.get("importance", "").lower()
    prio = headers.get("x-priority", "").strip()
    if imp == "high" or prio.startswith(("1", "2")):
        return "high"
    if imp == "low" or prio.startswith(("4", "5")):
        return "low"
    return "normal"


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _extract_text(payload: dict) -> str:
    plain, html_parts = [], []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            html_parts.append(_decode(data))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    if html_parts:
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(html_parts))
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", html.unescape(text)).strip()
    return ""
