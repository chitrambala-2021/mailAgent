"""Phone push notifications via ntfy (https://ntfy.sh or self-hosted)."""
from __future__ import annotations

import requests

from ..config_loader import env
from .base import Notifier, NotificationItem, build_body, build_title

NTFY_PRIORITY = {"high": 5, "medium": 3, "low": 2}


class NtfyNotifier(Notifier):
    name = "ntfy"

    def send(self, items: list[NotificationItem]) -> None:
        server = (self.cfg.get("server") or "https://ntfy.sh").rstrip("/")
        topic = self.cfg.get("topic")
        if not topic:
            raise RuntimeError("notifications.channels.ntfy.topic is required")

        priorities = [NTFY_PRIORITY[i.priority] for i in items if i.priority in NTFY_PRIORITY]
        if not priorities:
            priorities = [4 if any(i.email.importance == "high" for i in items) else 3]

        payload = {
            "topic": topic,
            "title": build_title(items),
            "message": build_body(items)[:3500],
            "priority": max(priorities),
            "tags": ["email"],
        }
        if len(items) == 1 and items[0].email.web_link:
            payload["click"] = items[0].email.web_link

        headers = {}
        token = env("NTFY_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        # JSON publishing to the server root handles non-ASCII titles safely
        requests.post(server, json=payload, headers=headers, timeout=10).raise_for_status()
