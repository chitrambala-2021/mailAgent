"""Decides whether an email should trigger a notification."""
from __future__ import annotations

from .providers.base import Email

# Alerts sent by the email notifier carry this prefix; never notify on them
# (prevents a loop when alerts are mailed to a monitored inbox).
SELF_TAG = "[Mail Notifier]"


def should_notify(email: Email, filters_cfg: dict) -> bool:
    if email.subject.startswith(SELF_TAG):
        return False

    if filters_cfg.get("mode", "all") == "all":
        return True

    rules = filters_cfg.get("rules", {}) or {}
    senders = [s.strip().lower() for s in rules.get("senders") or [] if s.strip()]
    keywords = [k.strip().lower() for k in rules.get("subject_keywords") or [] if k.strip()]

    # Gate: importance
    if rules.get("high_importance_only") and email.importance != "high":
        return False

    # No sender/keyword rules -> everything that passed the gate is notified
    if not senders and not keywords:
        return True

    return _sender_matches(email.sender_email, senders) or _keyword_matches(email.subject, keywords)


def _sender_matches(sender: str, patterns: list[str]) -> bool:
    sender = sender.lower()
    for p in patterns:
        if p.startswith("@") and sender.endswith(p):
            return True
        if "@" not in p and sender.endswith("@" + p):
            return True
        if sender == p:
            return True
    return False


def _keyword_matches(subject: str, keywords: list[str]) -> bool:
    subject = subject.lower()
    return any(k in subject for k in keywords)
