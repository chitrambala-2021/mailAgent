"""Email alerts via SMTP. (Named smtp_email.py to avoid clashing with Python's `email` module.)"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from ..config_loader import env
from ..filters import SELF_TAG
from .base import Notifier, NotificationItem, build_line, build_title


class EmailNotifier(Notifier):
    name = "email"

    def send(self, items: list[NotificationItem]) -> None:
        host = env("SMTP_HOST")
        to_addr = self.cfg.get("to")
        if not host or not to_addr:
            raise RuntimeError("SMTP_HOST in .env and notifications.channels.email.to are required")

        port = int(env("SMTP_PORT", "587"))
        user = env("SMTP_USER")
        password = env("SMTP_PASSWORD")
        from_addr = env("SMTP_FROM", user or to_addr)

        lines = []
        for it in items:
            e = it.email
            lines.append(build_line(it))
            lines.append(f"   From: {e.sender_display}  |  Account: {e.account}")
            if e.web_link:
                lines.append(f"   Open: {e.web_link}")
            lines.append("")

        msg = EmailMessage()
        msg["Subject"] = f"{SELF_TAG} {build_title(items)}"  # tag prevents notification loops
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.set_content("\n".join(lines))

        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as s:
                if user:
                    s.login(user, password or "")
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=context)
                if user:
                    s.login(user, password or "")
                s.send_message(msg)
