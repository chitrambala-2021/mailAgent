"""macOS Notification Center alerts.

Uses `terminal-notifier` if installed (click opens the mail),
otherwise falls back to built-in `osascript`.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys

from .base import Notifier, NotificationItem, build_body, build_title

log = logging.getLogger(__name__)


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class MacOSNotifier(Notifier):
    name = "macos"

    def send(self, items: list[NotificationItem]) -> None:
        if sys.platform != "darwin":
            log.warning("macOS notifier skipped (not running on macOS)")
            return

        title = build_title(items)
        body = build_body(items)
        subtitle = items[0].email.account if len(items) == 1 else ""
        sound = self.cfg.get("sound", "default") or ""
        link = items[0].email.web_link if len(items) == 1 else ""

        notifier_bin = shutil.which("terminal-notifier")
        if notifier_bin:
            cmd = [notifier_bin, "-title", title, "-message", body[:250], "-group", "mail-notifier"]
            if subtitle:
                cmd += ["-subtitle", subtitle]
            if sound:
                cmd += ["-sound", sound]
            if link:
                cmd += ["-open", link]
        else:
            script = f'display notification "{_esc(body[:250])}" with title "{_esc(title)}"'
            if subtitle:
                script += f' subtitle "{_esc(subtitle)}"'
            if sound:
                script += f' sound name "{_esc(sound)}"'
            cmd = ["osascript", "-e", script]

        subprocess.run(cmd, check=True, capture_output=True, timeout=10)
