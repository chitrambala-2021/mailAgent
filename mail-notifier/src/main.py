"""Mail Notifier entry point.

Usage (from the project root):
  python -m src.main                 # run forever, polling every N minutes
  python -m src.main --once          # single poll, then exit
  python -m src.main --login         # sign in to every configured account, then exit
  python -m src.main --detect EMAIL  # show which provider an address uses
  python -m src.main --test-notify   # send a sample alert to every enabled channel
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from .ai_triage import Triage
from .config_loader import ConfigError, load_settings, resolve_path
from .filters import should_notify
from .notifiers import build_notifiers
from .notifiers.base import NotificationItem
from .providers.base import AuthRequiredError, Email, MailProvider
from .providers.detector import ProviderDetectionError, detect_provider, resolve_provider
from .providers.factory import create_provider
from .state import StateStore

log = logging.getLogger("mail_notifier")

OVERLAP = timedelta(minutes=2)  # re-check a small window; seen-IDs prevent duplicates


class App:
    def __init__(self, settings: dict, interactive: bool):
        self.settings = settings
        self.interactive = interactive
        self.state = StateStore(resolve_path(settings.get("state_file", "data/state.json")))
        self.triage = Triage(settings.get("ai_triage", {}))
        self.notifiers = build_notifiers(settings)
        self.providers: dict[str, MailProvider] = {}
        self._stop = False

    # ---------- accounts / providers ----------
    def accounts(self) -> list[dict]:
        return [a for a in self.settings["accounts"] if a.get("enabled", True)]

    def get_provider(self, account: dict) -> MailProvider:
        email = account["email"].strip()
        if email in self.providers:
            return self.providers[email]

        configured = str(account.get("provider", "auto")).lower()
        name = self.state.get_provider(email) if configured == "auto" else None
        if not name:
            name = resolve_provider(account)
            if configured == "auto":
                self.state.set_provider(email, name)
                self.state.save()
        log.info("%s -> %s", email, name)

        provider = create_provider(email, name, self.settings)
        provider.authenticate(interactive=self.interactive)
        self.providers[email] = provider
        return provider

    # ---------- polling ----------
    def poll_account(self, account: dict) -> list[NotificationItem]:
        email = account["email"].strip()
        provider = self.get_provider(account)

        started = datetime.now(timezone.utc)
        last = self.state.get_last_check(email)
        if last:
            since = last - OVERLAP
        else:
            since = started - timedelta(minutes=int(self.settings.get("first_run_lookback_minutes", 60)))

        filters_cfg = self.settings.get("filters", {}) or {}
        emails = provider.fetch_new(
            since,
            limit=int(self.settings.get("max_emails_per_poll", 50)),
            unread_only=filters_cfg.get("unread_only", True),
        )

        new: list[Email] = [e for e in emails if not self.state.is_seen(email, e.id)]
        new.sort(key=lambda e: e.received_at)

        items: list[NotificationItem] = []
        for e in new:
            if not should_notify(e, filters_cfg):
                continue
            result = self.triage.analyze(e)
            if not self.triage.passes_threshold(result):
                log.debug("Skipped by AI priority: %s", e.subject)
                continue
            items.append(NotificationItem(e, result))

        self.state.mark_seen(email, [e.id for e in new])
        self.state.set_last_check(email, started)
        log.info("[%s] %d new, %d to notify", email, len(new), len(items))
        return items

    def run_once(self) -> None:
        all_items: list[NotificationItem] = []
        for account in self.accounts():
            email = account["email"].strip()
            try:
                all_items.extend(self.poll_account(account))
            except ProviderDetectionError as exc:
                log.error("[%s] %s", email, exc)
            except AuthRequiredError as exc:
                log.error("%s", exc)
                self.providers.pop(email, None)
            except Exception as exc:
                log.exception("[%s] Poll failed: %s", email, exc)
                self.providers.pop(email, None)  # rebuild next cycle

        self.dispatch(all_items)
        self.state.save()

    def dispatch(self, items: list[NotificationItem]) -> None:
        if not items:
            return
        if not self.notifiers:
            log.warning("%d alerts but no notification channel is enabled", len(items))
            return

        batch = (self.settings.get("notifications") or {}).get("batch_mode", False)
        for notifier in self.notifiers:
            if batch:
                notifier.send_safe(items)
            else:
                for item in items:
                    notifier.send_safe([item])

    def run_forever(self) -> None:
        interval = float(self.settings.get("poll_interval_minutes", 5)) * 60
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)

        log.info("Mail Notifier started: %d account(s), every %s min, channels: %s",
                 len(self.accounts()), interval / 60,
                 ", ".join(n.name for n in self.notifiers) or "none")

        while not self._stop:
            self.run_once()
            waited = 0.0
            while waited < interval and not self._stop:
                time.sleep(1)
                waited += 1
        log.info("Mail Notifier stopped")

    def _handle_stop(self, *_):
        self._stop = True

    # ---------- utilities ----------
    def login_all(self) -> int:
        failures = 0
        for account in self.accounts():
            try:
                self.get_provider(account)
                print(f"✓ {account['email']} signed in")
            except Exception as exc:
                failures += 1
                print(f"✗ {account['email']}: {exc}")
        self.state.save()
        return 1 if failures else 0

    def test_notify(self) -> int:
        if not self.notifiers:
            print("No notification channel is enabled in settings.yaml")
            return 1
        sample = Email(
            id="test", account="test@example.com", provider="test",
            subject="Test notification from Mail Notifier",
            sender_email="sender@example.com", sender_name="Mail Notifier",
            received_at=datetime.now(timezone.utc),
            snippet="If you can read this, the channel works.",
        )
        ok = True
        for n in self.notifiers:
            sent = n.send_safe([NotificationItem(sample)])
            print(f"{'✓' if sent else '✗'} {n.name}")
            ok = ok and sent
        return 0 if ok else 1


def setup_logging(settings: dict) -> None:
    level = getattr(logging, str(settings.get("log_level", "INFO")).upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_file = settings.get("log_file")
    if log_file:
        path = resolve_path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    for noisy in ("googleapiclient", "urllib3", "msal", "httpx", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    parser = argparse.ArgumentParser(description="Gmail / Outlook new-mail notifier")
    parser.add_argument("--config", help="path to settings.yaml")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    parser.add_argument("--login", action="store_true", help="sign in to all accounts and exit")
    parser.add_argument("--detect", metavar="EMAIL", help="show detected provider for an address")
    parser.add_argument("--test-notify", action="store_true", help="send a test alert to all channels")
    args = parser.parse_args()

    if args.detect:
        try:
            print(f"{args.detect} -> {detect_provider(args.detect)}")
            return 0
        except ProviderDetectionError as exc:
            print(exc)
            return 1

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}")
        return 2

    setup_logging(settings)
    interactive = args.login or sys.stdin.isatty()
    app = App(settings, interactive=interactive)

    if args.login:
        return app.login_all()
    if args.test_notify:
        return app.test_notify()
    if args.once:
        app.run_once()
        return 0

    app.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
