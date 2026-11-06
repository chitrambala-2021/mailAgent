"""Notification item model, shared formatting and the notifier interface."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..ai_triage import TriageResult
from ..providers.base import Email

log = logging.getLogger(__name__)

PRIORITY_ICON = {"high": "🔴", "medium": "🟡", "low": "⚪"}


@dataclass
class NotificationItem:
    email: Email
    triage: TriageResult | None = None

    @property
    def priority(self) -> str | None:
        return self.triage.priority if self.triage else None

    @property
    def summary(self) -> str:
        return self.triage.summary if self.triage else ""

    @property
    def icon(self) -> str:
        if self.priority:
            return PRIORITY_ICON.get(self.priority, "")
        return "❗" if self.email.importance == "high" else ""


def build_title(items: list[NotificationItem]) -> str:
    if len(items) == 1:
        it = items[0]
        who = it.email.sender_name or it.email.sender_email
        return f"{it.icon} {who}".strip()
    return f"📬 {len(items)} new emails"


def build_line(item: NotificationItem) -> str:
    e = item.email
    line = f"{item.icon} {e.sender_name or e.sender_email}: {e.subject}".strip()
    if item.summary:
        line += f" — {item.summary}"
    return line


def build_body(items: list[NotificationItem]) -> str:
    if len(items) == 1:
        it = items[0]
        text = it.email.subject
        detail = it.summary or it.email.snippet
        return f"{text}\n{detail[:200]}" if detail else text
    return "\n".join(build_line(i) for i in items)


class Notifier(ABC):
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}

    @abstractmethod
    def send(self, items: list[NotificationItem]) -> None:
        ...

    def send_safe(self, items: list[NotificationItem]) -> bool:
        try:
            self.send(items)
            return True
        except Exception as exc:
            log.error("Notifier '%s' failed: %s", self.name, exc)
            return False
