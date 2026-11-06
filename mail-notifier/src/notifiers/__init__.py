"""Builds the list of enabled notifiers from settings."""
from __future__ import annotations

import logging

from .base import Notifier
from .macos import MacOSNotifier
from .ntfy import NtfyNotifier
from .slack import SlackNotifier
from .smtp_email import EmailNotifier
from .teams import TeamsNotifier

log = logging.getLogger(__name__)

REGISTRY: dict[str, type[Notifier]] = {
    "macos": MacOSNotifier,
    "slack": SlackNotifier,
    "teams": TeamsNotifier,
    "email": EmailNotifier,
    "ntfy": NtfyNotifier,
}


def build_notifiers(settings: dict) -> list[Notifier]:
    channels = (settings.get("notifications") or {}).get("channels") or {}
    notifiers = []
    for name, cfg in channels.items():
        if not (cfg or {}).get("enabled"):
            continue
        cls = REGISTRY.get(name)
        if cls is None:
            log.warning("Unknown notification channel '%s' ignored", name)
            continue
        notifiers.append(cls(cfg))
    return notifiers
