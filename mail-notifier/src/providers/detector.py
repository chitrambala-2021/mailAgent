"""Detects whether an email address is hosted on Gmail (Google Workspace) or Outlook (M365).

Order of checks:
  1. Known public domains (gmail.com, outlook.com, ...)
  2. MX records  (aspmx.l.google.com / *.mail.protection.outlook.com)
  3. SPF TXT record (include:_spf.google.com / include:spf.protection.outlook.com)
     -> helps when MX points to a security gateway (Mimecast, Proofpoint, ...)
"""
from __future__ import annotations

import logging
from functools import lru_cache

import dns.exception
import dns.resolver

log = logging.getLogger(__name__)

GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}
OUTLOOK_DOMAINS = {
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "outlook.in", "hotmail.co.uk", "live.in", "live.co.uk",
}

GMAIL_MX_SUFFIXES = ("google.com", "googlemail.com")
OUTLOOK_MX_SUFFIXES = ("protection.outlook.com", "outlook.com", "hotmail.com")

GMAIL_SPF_HINTS = ("_spf.google.com",)
OUTLOOK_SPF_HINTS = ("spf.protection.outlook.com",)


class ProviderDetectionError(Exception):
    pass


def resolve_provider(account: dict) -> str:
    """Return 'gmail' or 'outlook' for an account entry from settings.yaml."""
    configured = str(account.get("provider", "auto")).lower()
    if configured in ("gmail", "outlook"):
        return configured
    return detect_provider(account["email"])


def detect_provider(email: str) -> str:
    domain = email.strip().rsplit("@", 1)[-1].lower()

    if domain in GMAIL_DOMAINS:
        return "gmail"
    if domain in OUTLOOK_DOMAINS:
        return "outlook"

    mx_hosts = _lookup(domain, "MX")
    for host in mx_hosts:
        if host.endswith(GMAIL_MX_SUFFIXES):
            return "gmail"
        if host.endswith(OUTLOOK_MX_SUFFIXES):
            return "outlook"

    txt_records = " ".join(_lookup(domain, "TXT")).lower()
    if any(h in txt_records for h in GMAIL_SPF_HINTS):
        return "gmail"
    if any(h in txt_records for h in OUTLOOK_SPF_HINTS):
        return "outlook"

    raise ProviderDetectionError(
        f"Could not detect provider for '{domain}' (MX: {', '.join(mx_hosts) or 'none'}). "
        f"Set provider: gmail or provider: outlook for this account in settings.yaml."
    )


@lru_cache(maxsize=128)
def _lookup(domain: str, rtype: str) -> tuple[str, ...]:
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5.0
    try:
        answers = resolver.resolve(domain, rtype)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return ()
    except dns.exception.Timeout:
        log.warning("DNS %s lookup timed out for %s", rtype, domain)
        return ()

    if rtype == "MX":
        records = sorted(answers, key=lambda r: r.preference)
        return tuple(str(r.exchange).rstrip(".").lower() for r in records)
    return tuple(
        b"".join(r.strings).decode("utf-8", errors="ignore") for r in answers
    )
