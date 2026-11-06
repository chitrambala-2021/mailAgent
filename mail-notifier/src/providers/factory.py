"""Creates the right provider instance for a provider name."""
from __future__ import annotations

from .base import MailProvider


def create_provider(email: str, provider_name: str, settings: dict) -> MailProvider:
    if provider_name == "gmail":
        from .gmail import GmailProvider  # lazy import: only load what's used
        return GmailProvider(email, settings)
    if provider_name == "outlook":
        from .outlook import OutlookProvider
        return OutlookProvider(email, settings)
    raise ValueError(f"Unknown provider: {provider_name}")
