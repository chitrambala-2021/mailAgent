"""Common email model and provider interface."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


class AuthRequiredError(Exception):
    """Login is missing/expired and can't be completed non-interactively."""


@dataclass
class Email:
    id: str
    account: str
    provider: str
    subject: str
    sender_email: str
    sender_name: str
    received_at: datetime
    snippet: str = ""
    body: str = ""
    importance: str = "normal"  # low | normal | high
    web_link: str = ""

    @property
    def sender_display(self) -> str:
        if self.sender_name and self.sender_name != self.sender_email:
            return f"{self.sender_name} <{self.sender_email}>"
        return self.sender_email


class MailProvider(ABC):
    name = "base"

    def __init__(self, email: str, settings: dict):
        self.email = email
        self.settings = settings

    @abstractmethod
    def authenticate(self, interactive: bool = True) -> None:
        """Load or obtain credentials. Raise AuthRequiredError if impossible."""

    @abstractmethod
    def fetch_new(self, since: datetime, limit: int, unread_only: bool = True) -> list[Email]:
        """Return emails received at/after `since` (newest first is fine)."""

    @property
    def safe_id(self) -> str:
        """Filesystem-safe name for token files."""
        return re.sub(r"[^a-zA-Z0-9_.-]", "_", self.email.lower())
