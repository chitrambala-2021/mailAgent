"""Persists per-account state: last check time, seen message IDs, detected provider."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


class StateStore:
    MAX_SEEN = 500  # message IDs remembered per account (dedupe window)

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = self._load()

    # ---------- persistence ----------
    def _load(self) -> dict:
        if not self.path.exists():
            return {"accounts": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("accounts", {})
            return data
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("State file unreadable (%s); starting fresh", exc)
            return {"accounts": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, self.path)  # atomic

    # ---------- helpers ----------
    def _acct(self, email: str) -> dict:
        return self._data["accounts"].setdefault(
            email.lower(), {"last_check": None, "seen_ids": [], "provider": None}
        )

    def get_last_check(self, email: str) -> datetime | None:
        value = self._acct(email).get("last_check")
        return datetime.fromisoformat(value) if value else None

    def set_last_check(self, email: str, when: datetime) -> None:
        self._acct(email)["last_check"] = when.isoformat()

    def is_seen(self, email: str, msg_id: str) -> bool:
        return msg_id in self._acct(email)["seen_ids"]

    def mark_seen(self, email: str, ids: list[str]) -> None:
        seen = self._acct(email)["seen_ids"]
        for msg_id in ids:
            if msg_id not in seen:
                seen.append(msg_id)
        if len(seen) > self.MAX_SEEN:
            del seen[: len(seen) - self.MAX_SEEN]

    def get_provider(self, email: str) -> str | None:
        return self._acct(email).get("provider")

    def set_provider(self, email: str, provider: str) -> None:
        self._acct(email)["provider"] = provider
