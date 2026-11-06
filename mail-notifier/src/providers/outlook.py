"""Outlook / Microsoft 365 provider (Microsoft Graph, delegated Mail.Read via MSAL device code)."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import msal
import requests

from ..config_loader import env, resolve_path
from .base import AuthRequiredError, Email, MailProvider

log = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
WELL_KNOWN_EXCLUDED = ("junkemail", "deleteditems", "sentitems", "drafts", "outbox")
SELECT = "id,subject,from,receivedDateTime,bodyPreview,body,importance,webLink,parentFolderId"


class OutlookProvider(MailProvider):
    name = "outlook"

    def __init__(self, email: str, settings: dict):
        super().__init__(email, settings)
        cfg = settings.get("outlook", {})
        self.client_id = env("OUTLOOK_CLIENT_ID")
        self.tenant = env("OUTLOOK_TENANT_ID", "organizations")
        self.scopes = cfg.get("scopes") or ["Mail.Read"]
        self.token_dir = resolve_path(cfg.get("token_dir", "data/tokens/outlook"))
        self.exclude_folders = [
            f.strip().lower() for f in settings.get("filters", {}).get("exclude_folders", []) or []
        ]
        self._cache = msal.SerializableTokenCache()
        self._app: msal.PublicClientApplication | None = None
        self._token: str | None = None
        self._session = requests.Session()
        self._excluded_ids: set[str] | None = None

    @property
    def cache_file(self):
        return self.token_dir / f"{self.safe_id}.bin"

    # ---------- auth ----------
    def authenticate(self, interactive: bool = True) -> None:
        if not self.client_id:
            raise AuthRequiredError("OUTLOOK_CLIENT_ID is missing in .env. See README (Outlook setup).")

        if self.cache_file.exists():
            self._cache.deserialize(self.cache_file.read_text(encoding="utf-8"))

        self._app = msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant}",
            token_cache=self._cache,
        )
        self._acquire(interactive)

    def _acquire(self, interactive: bool) -> None:
        result = None
        accounts = self._app.get_accounts(username=self.email)
        if accounts:
            result = self._app.acquire_token_silent(self.scopes, account=accounts[0])

        if not result:
            if not interactive:
                raise AuthRequiredError(
                    f"[{self.email}] Outlook login required. Run: python -m src.main --login"
                )
            flow = self._app.initiate_device_flow(scopes=self.scopes)
            if "user_code" not in flow:
                raise AuthRequiredError(f"Device login failed: {flow.get('error_description', flow)}")
            print(f"\n[{self.email}] {flow['message']}\n", flush=True)
            result = self._app.acquire_token_by_device_flow(flow)

            signed_in = (result.get("id_token_claims") or {}).get("preferred_username", "")
            if signed_in and signed_in.lower() != self.email.lower():
                log.warning("[%s] Signed in as %s - notifications will be for that mailbox",
                            self.email, signed_in)

        if "access_token" not in result:
            raise AuthRequiredError(
                f"[{self.email}] Outlook login failed: {result.get('error_description', result.get('error'))}"
            )

        self._token = result["access_token"]
        self._save_cache()

    def _save_cache(self) -> None:
        if self._cache.has_state_changed:
            self.token_dir.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(self._cache.serialize(), encoding="utf-8")
            os.chmod(self.cache_file, 0o600)

    # ---------- HTTP ----------
    def _get(self, url: str, params: dict | None = None, headers: dict | None = None,
             allow_404: bool = False) -> dict | None:
        hdrs = {"Authorization": f"Bearer {self._token}", **(headers or {})}
        for attempt in range(3):
            resp = self._session.get(url, params=params, headers=hdrs, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = int(resp.headers.get("Retry-After", 2 ** attempt * 5))
                log.warning("Graph throttled/unavailable (%s); retrying in %ss", resp.status_code, wait)
                time.sleep(min(wait, 60))
                continue
            if resp.status_code == 404 and allow_404:
                return None
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return None

    # ---------- fetch ----------
    def fetch_new(self, since: datetime, limit: int, unread_only: bool = True) -> list[Email]:
        if self._app is None:
            self.authenticate(interactive=False)
        else:
            self._acquire(interactive=False)  # refreshes silently when the token expires

        excluded = self._excluded_folder_ids()
        since_iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        flt = f"receivedDateTime ge {since_iso}"
        if unread_only:
            flt += " and isRead eq false"

        url: str | None = f"{GRAPH}/me/messages"
        params: dict | None = {
            "$filter": flt,
            "$orderby": "receivedDateTime desc",
            "$top": str(min(limit, 50)),
            "$select": SELECT,
        }
        headers = {"Prefer": 'outlook.body-content-type="text"'}

        emails: list[Email] = []
        while url and len(emails) < limit:
            data = self._get(url, params=params, headers=headers) or {}
            params = None  # nextLink already contains the query
            for m in data.get("value", []):
                if m.get("parentFolderId") in excluded:
                    continue
                emails.append(self._to_email(m))
                if len(emails) >= limit:
                    break
            url = data.get("@odata.nextLink")
        return emails

    def _excluded_folder_ids(self) -> set[str]:
        if self._excluded_ids is not None:
            return self._excluded_ids

        ids: set[str] = set()
        for wk in WELL_KNOWN_EXCLUDED:
            folder = self._get(f"{GRAPH}/me/mailFolders/{wk}", params={"$select": "id"}, allow_404=True)
            if folder:
                ids.add(folder["id"])

        if self.exclude_folders:
            data = self._get(f"{GRAPH}/me/mailFolders",
                             params={"$top": "200", "$select": "id,displayName"}) or {}
            for f in data.get("value", []):
                if f.get("displayName", "").lower() in self.exclude_folders:
                    ids.add(f["id"])

        self._excluded_ids = ids
        return ids

    def _to_email(self, m: dict) -> Email:
        sender = (m.get("from") or {}).get("emailAddress") or {}
        received = datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00"))
        return Email(
            id=m["id"],
            account=self.email,
            provider=self.name,
            subject=m.get("subject") or "(no subject)",
            sender_email=(sender.get("address") or "").lower(),
            sender_name=sender.get("name") or "",
            received_at=received,
            snippet=m.get("bodyPreview", ""),
            body=((m.get("body") or {}).get("content") or "").strip(),
            importance=(m.get("importance") or "normal").lower(),
            web_link=m.get("webLink", ""),
        )
