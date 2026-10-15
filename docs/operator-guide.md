# Operator guide

The default Compose stack serves offline replay data. It does not start the optional collector, scheduler or executor services. Production release is pending concrete build review; do not infer deployment from the checked-in Wrangler configuration.

## Local operation

Copy `.env.example` to private `.env`, then use `make dev-up`. The initializer applies Alembic migrations and seeds the deterministic replay before the API starts. `make logs` shows service logs; `make dev-down` stops the stack while preserving its database volume. Set `DB_PORT`, `API_PORT` or `WEB_PORT` before startup if the default loopback ports are occupied.

Readiness is exposed at `/readyz`, process liveness at `/healthz`. The public API is under `/api/v1/public/`. Admin requests use `/api/v1/admin/` and require an authenticated administrator. Create the first local user using the interactive bootstrap command in the README; no default admin password exists.

Do not reuse a competition database for tests. Use a disposable PostgreSQL database and set `TEST_DATABASE_URL`. Offline replay seeding and an actual worker restart test are different checks; the validation record identifies which ran.

## Evidence and failures

Keep canonical snapshots, exact sent request bytes, returned visible decisions and their hashes. Database migrations protect evidence tables from alteration. Provider transport headers and credentials are not public evidence. Never put keys in frontend variables, URLs, screenshots or logs.

A pending job may be claimed again after its lease expires if no dispatch was recorded. A recorded uncertain external dispatch must be audited and terminalized without retrying the paid call. Before recovering a stopped worker, inspect durable jobs, attempts, fences and reservations; do not reset them to manufacture a successful round.

Run-level inference reservations and the global UTC daily reservation cap are separate bounds. Unknown billing remains unknown. Reservation assumptions are not provider price claims and provider costs are separate from trading equity.

## Backup and restore

`make backup` writes a custom-format PostgreSQL dump under `backups/` with private file permissions. Keep an encrypted copy outside the server and practice recovery using a disposable instance. Dumps include sensitive operator metadata and must not enter the public repository.

Restore replaces the selected local Compose database contents. The script requires both an existing dump and an explicit target marker:

```sh
RESTORE_TARGET=local-dev-confirmed RESTORE_FILE=backups/arena-example.dump make restore
```

Stop writers for a recovery operation, restore, check Alembic revision and readiness, then compare persisted evidence hashes and balanced ledger totals before resuming. A successful dump alone is not restore verification. Actual recovery checks appear in the implementation record.

## Cloudflare release boundary

The frontend target is `arena.leonfuller.com`; the fixed Tunnel origin is `arena-origin.leonfuller.com`. Configure service-authenticated Tunnel transport separately from visitor Access identity. Both Worker and API verify admin identity. Protect admin HTML, its assets and admin API paths. Keep Tailscale available for server recovery.

The Worker has no production route or public preview endpoint enabled. Before release, review the concrete build, account-owned rate-limit namespace, Access issuer/audience/subject policy, private origin secrets and Tunnel health. API requests fail closed while required bindings are absent. Connect previews only to fixture or staging data.

Use the [Worker guide](../deploy/worker/README.md) for exact variables and dry-run commands. Combined static assets and API handling follow [Cloudflare Workers Static Assets](https://developers.cloudflare.com/workers/static-assets/); visitor JWT validation follows [Cloudflare's validation guidance](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/). Account resources, DNS and production routing have not been verified or changed by this implementation checkpoint.
