"""Microsoft Teams alerts via a Teams Workflows webhook (Adaptive Card)."""
from __future__ import annotations

import requests

from ..config_loader import env
from .base import Notifier, NotificationItem, build_title


class TeamsNotifier(Notifier):
    name = "teams"

    def send(self, items: list[NotificationItem]) -> None:
        url = env("TEAMS_WEBHOOK_URL")
        if not url:
            raise RuntimeError("TEAMS_WEBHOOK_URL is not set in .env")

        body = [{"type": "TextBlock", "text": build_title(items), "weight": "Bolder", "size": "Medium", "wrap": True}]
        for it in items:
            e = it.email
            block = [
                {"type": "TextBlock", "text": f"{it.icon} {e.subject}", "weight": "Bolder", "wrap": True},
                {"type": "TextBlock", "text": f"From: {e.sender_display} · {e.account}",
                 "isSubtle": True, "spacing": "None", "wrap": True},
            ]
            if it.summary:
                block.append({"type": "TextBlock", "text": it.summary, "wrap": True})
            body.append({"type": "Container", "separator": True, "items": block})

        card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body,
        }
        if len(items) == 1 and items[0].email.web_link:
            card["actions"] = [{"type": "Action.OpenUrl", "title": "Open mail", "url": items[0].email.web_link}]

        payload = {
            "type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}],
        }
        requests.post(url, json=payload, timeout=10).raise_for_status()
