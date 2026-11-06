# Mail Notifier

Watches **Gmail / Google Workspace** and **Outlook / Microsoft 365** inboxes and sends alerts for new mail.
The provider is picked automatically from each email address (domain → MX → SPF records).

- Read-only access (`gmail.readonly`, `Mail.Read`). It never sends, moves or deletes mail.
- Multiple accounts, mixed providers.
- Channels: macOS, Slack, Teams, email (SMTP), phone push (ntfy).
- Optional Claude triage: priority and a one-line summary.

---

## 1. Install (macOS, Python 3.10+)

```bash
cd mail-notifier
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env
brew install terminal-notifier   # optional: clicking a macOS alert opens the mail
```

## 2. Configure

Edit `config/settings.yaml`:
- `accounts`: your email addresses (`provider: auto` is fine).
- `notifications.channels`: enable what you want.

Check what an address resolves to:

```bash
python -m src.main --detect you@company.com
```

## 3. Gmail / Google Workspace setup

1. In Google Cloud Console, create a project and **enable the Gmail API**.
2. **OAuth consent screen**: set it to *Internal* for a Workspace org, or *External* plus add yourself as a test user.
3. **Credentials → Create OAuth client ID → Desktop app.** Download the JSON.
4. Save it as `config/gmail_credentials.json`.

> Work accounts: your Workspace admin may need to allow the app (API controls).

## 4. Outlook / Microsoft 365 setup

1. Entra ID (Azure AD), then **App registrations → New registration**.
   - Supported accounts: *this org* (or multi-tenant if needed).
2. **Authentication**:
   - Add the *Mobile and desktop applications* platform with redirect `https://login.microsoftonline.com/common/oauth2/nativeclient`.
   - Set **Allow public client flows = Yes** (needed for device-code login).
3. **API permissions**: Microsoft Graph, *Delegated*, `Mail.Read`. Ask your admin to grant consent if required.
4. Put the **Application (client) ID** in `.env` as `OUTLOOK_CLIENT_ID`.
5. Optionally set `OUTLOOK_TENANT_ID` to your tenant ID or domain (the default is `organizations`).

## 5. Sign in (once per account)

```bash
python -m src.main --login
```

- Gmail opens a browser window.
- Outlook prints a code to enter at microsoft.com/devicelogin.
- Tokens are saved in `data/tokens/` with `600` permissions. They refresh automatically.

## 6. Run

```bash
python -m src.main --test-notify   # check your channels
python -m src.main --once          # one poll
python -m src.main                 # keep running
```

## 7. Run in the background (launchd)

1. Edit the paths in `deploy/com.mailnotifier.plist`.
2. Load it:

```bash
cp deploy/com.mailnotifier.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mailnotifier.plist
```

Logs go to `data/notifier.log`.

---

## Channel setup

| Channel | What to set |
|---|---|
| macOS | Nothing. Allow notifications for Terminal / terminal-notifier in System Settings. |
| Slack | `SLACK_WEBHOOK_URL` (create an Incoming Webhook app). |
| Teams | `TEAMS_WEBHOOK_URL` from Teams → Workflows → *"Send webhook alerts to a channel"*. |
| Email | `SMTP_*` in `.env` and `channels.email.to`. Alerts are tagged `[Mail Notifier]` so they never trigger themselves. |
| ntfy | Install the ntfy app, subscribe to a hard-to-guess `topic`, and set it in the config. |

## AI triage (optional)

1. Set `ai_triage.enabled: true` and add `ANTHROPIC_API_KEY` to `.env`.
2. Use `min_priority_to_notify: medium` to silence newsletters and other low-priority mail.
3. Email content goes to the Claude API only when this option is on.

## How it avoids duplicates

- `data/state.json` stores each account's last check time and the last 500 message IDs.
- Each poll re-checks a 2-minute overlap. IDs that were already seen are skipped.

## Troubleshooting

- **"Could not detect provider"**: your MX points to a mail gateway. Set `provider: gmail` or `provider: outlook` for that account.
- **"login required"** in the logs: run `python -m src.main --login` again.
- **AADSTS65001 / admin approval required**: your M365 admin needs to grant consent for `Mail.Read`.
