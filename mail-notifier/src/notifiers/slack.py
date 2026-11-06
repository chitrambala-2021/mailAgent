"""Slack alerts via Incoming Webhook."""
from __future__ import annotations

import requests

from ..config_loader import env
from .base import Notifier, NotificationItem, build_title


class SlackNotifier(Notifier):
    name = "slack"

    def send(self, items: list[NotificationItem]) -> None:
        url = env("SLACK_WEBHOOK_URL")
        if not url:
            raise RuntimeError("SLACK_WEBHOOK_URL is not set in .env")

        lines = []
        for it in items:
            e = it.email
            subject = f"<{e.web_link}|{e.subject}>" if e.web_link else e.subject
            line = f"{it.icon} *{subject}*\nFrom: {e.sender_display}  ·  _{e.account}_"
            if it.summary:
                line += f"\n> {it.summary}"
            lines.append(line)

        payload = {
            "text": build_title(items),
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": build_title(items)[:150]}},
                {"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(lines)[:2900]}},
            ],
        }
        requests.post(url, json=payload, timeout=10).raise_for_status()
