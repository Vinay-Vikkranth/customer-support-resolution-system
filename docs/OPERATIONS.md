# Operations runbook

## First launch

1. Install Python dependencies and run `python launcher.py start` (or double-click Start-ResolveDesk.cmd on Windows).
2. Use the reviewer token in data/launcher/LOCAL_ACCESS.txt, or create named users with manage.py.
3. Confirm `/health`, sign-in, a case investigation and an approval.
4. Keep `.env`, databases and backups out of Git. `.gitignore` excludes local data and credentials.

The launcher starts a persistent hidden service on localhost, waits for its health check and saves its process identity. Closing the startup window does not stop the server. Use `python launcher.py status` to check and `python launcher.py stop` to stop. Restart after reboot. Keep LOCAL_ACCESS.txt private. A different process using the port will be left alone. `python run.py` remains a foreground developer option and stops when its terminal closes. Configuration uses `.env` (simple KEY=value, no shell expansion) with process environment taking precedence. Empty optional values do not enable integrations.

## Remote deployment

Run one application instance with persistent storage. Use HTTPS at the reverse proxy, disable development tokens, and create named users through the server administration command. Put additional request/rate limits at the proxy. Do not expose the reference account API publicly; use a private network and a long random shared secret. Do not expose SQLite files or backup directories through the web server.

The included Compose configuration binds the UI to loopback. The integration override adds a private account service with a separate volume. Both services need the same ACCOUNT_API_TOKEN. This is not multi-tenant or SSO software. Do not advertise it as production-ready without an environment-specific review.

## Recovery

| Symptom | Action |
|---|---|
| Outdated proposal | Re-investigate to gather current evidence. |
| Invalid AI output / provider outage | Local policy fallback remains available; inspect mode in the trace. |
| Account API unavailable | Restore connectivity. The app deliberately does not fall back to a different account store. |
| Uncertain remote execution | Retry approval on the same proposal; the operation ledger prevents duplicate execution. |
| Expired session | Sign in again. |
| Login throttled | Wait 15 minutes; investigate repeated failed attempts. |
| Incorrect manual closure | Reopen with a reason; preserve history. |
| Zendesk import error | Check server credentials, ticket ID and account mapping. No external ticket has been changed. |

## Backups

`python manage.py backup backups/DATE.db` uses SQLite's online backup API and refuses to overwrite an existing destination. Backups contain user hashes and case data; protect access. For a restore, stop the application, preserve the current database, place the backup at RESOLVEDESK_DB, then restart and run `python manage.py check`. If using the independent account service, back up its database too. Preserve both databases together to retain operation reconciliation history; do not reset only one and reuse old proposals.

## Monitoring

The API returns X-Request-ID and emits request method, path, status and duration. It does not log authorization headers, passwords, ticket bodies or model prompts. The reviewer Operations panel exposes model-mode counts, measured tokens and recent audit events. Dollar cost is unknown unless reconciled with the provider's actual pricing/billing. The daily investigation guard is not an atomic spending reservation; enforce hard billing limits at the provider as needed.

## Configuration

| Variable | Purpose |
|---|---|
| RESOLVEDESK_DB | Persistent application database path |
| RESOLVEDESK_DISABLE_TOKENS | Set 1 to require named users |
| RESOLVEDESK_TOKEN / RESOLVEDESK_REVIEW_TOKEN | Optional separate local development credentials |
| OPENAI_API_KEY / OPENAI_MODEL | Enable structured AI analysis |
| RESOLVEDESK_DAILY_AI_LIMIT | Recorded investigation threshold over the last 24 hours |
| ACCOUNT_API_URL / ACCOUNT_API_TOKEN | Optional authenticated account service |
| ACCOUNT_DB | Reference account service database |
| ZENDESK_SUBDOMAIN / ZENDESK_EMAIL / ZENDESK_API_TOKEN | Optional read-only import |

## Boundaries

No automatic customer replies, billing updates, live email sends, cloud resources or third-party account changes are created by installation. Enabling AI sends ticket evidence to the model provider. Enable real integrations only with appropriate access and data authorization.
