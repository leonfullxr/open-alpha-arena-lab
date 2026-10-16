# Operator guide

The default Compose stack serves offline replay data. It does not start the optional collector, scheduler, or executor services. The approved landing and simulation frontend are live on the persistent Workers.dev host. The backend and proposed custom-domain route remain unconfigured. The [session closeout](session-closeout-2026-10-16.md) records the current release boundary and cleanup.

## Local operation

Copy `.env.example` to private `.env`, then use `make dev-up`. The initializer applies Alembic migrations and seeds the deterministic replay before the API starts. `make logs` shows service logs; `make dev-down` stops the stack while preserving its database volume. Set `DB_PORT`, `API_PORT` or `WEB_PORT` before startup if the default loopback ports are occupied.

Readiness is exposed at `/readyz`, process liveness at `/healthz`. The public API is under `/api/v1/public/`. Admin requests use `/api/v1/admin/` and require an authenticated administrator. Create the first local user using the interactive bootstrap command in the README; no default admin password exists.

Do not reuse a competition database for tests. Use a disposable PostgreSQL database and set `TEST_DATABASE_URL`. Offline replay seeding and an actual worker restart test are different checks; the validation record identifies which ran.

## Live paper operation

Keep the default replay separate from a live experiment. Put provider credentials in the Debian process environment or a private Compose environment file. The supported adapters are `openai_chat`, `openai_responses`, and `opencode_go`; admin configuration stores the credential's environment-variable name. Do not put credential values in the browser.

For live collection, set `APP_MODE=live` and `MARKET_PROVIDER=hyperliquid`, then start the collector:

```sh
docker compose --profile workers up --build -d collector
```

Watch its heartbeat and public market freshness before enabling inference. Initial backfill stores 511 completed three-minute candles per symbol. Features use a fixed trailing window of 500 bars: EMA(20), Wilder RSI(7), and MACD(12,26,9), with SMA seeds at the window start. Snapshots freeze the latest twelve completed bars, their features, source times and the indicator policy. The first 499 stored bars are warmup records. Completed bars are immutable; a contradiction or gap is a data failure, not permission to rewrite prior evidence.

Create provider profiles, an original prompt version and a draft competition through `/admin/`. Baseline agents share a prompt. Each profile declares input/output limits, price assumptions and a maximum request reservation; the competition has a cumulative inference cap. Set `ENABLE_INFERENCE=true` explicitly before starting the scheduler. The ordinary worker processes are separate:

```sh
docker compose --profile workers up -d scheduler executor
```

Changing an environment file requires recreating the affected services; a plain container restart keeps its old environment. No broker or exchange trading credential is supported. All execution is paper accounting.

For the bounded integration smoke, keep the collector running, configure `OPENCODE_API_KEY` privately in the API container environment, and invoke:

```sh
docker compose exec api python -m app.cli live-smoke --config configs/live-smoke.example.json --rounds 5
```

This command sends genuine provider requests. The example fixes MiMo Flash and GLM Flash to five rounds at most, 80 KB request bodies, 1,000 output tokens, a $0.50 request reservation limit and a $2.50 run cap. The conservative reservation assumptions of $1/$3 per million input/output tokens are accounting bounds, not an invoice or a claim about provider prices. A missing key or invalid limit fails before market or provider access. Keep the collector separate so hourly funding evidence can be captured during a long model response. A failed or uncertain provider request is recorded without automatic retry; do not restart a failed smoke to disguise it. HOLD is a valid result.

The last genuine smoke sent ten requests, and all ten returned HTTP 429. Successful provider acceptance remains pending. Do not repeat those paid calls to close this session or claim a successful decision or fill.

## Evidence and failures

Keep canonical snapshots, exact sent request bytes, returned visible decisions and their hashes. Database migrations protect evidence tables from alteration. Provider transport headers and credentials are not public evidence. Never put keys in frontend variables, URLs, screenshots or logs.

A pending job may be claimed again after its lease expires if no dispatch was recorded. A recorded uncertain external dispatch must be audited and terminalized without retrying the paid call. Before recovering a stopped worker, inspect durable jobs, attempts, fences and reservations; do not reset them to manufacture a successful round.

Run `python -m app.cli reconcile` against the selected database after recovery. It compares account cash, realized PnL, fees, funding and reserved margin with the ledger, checks each journal, and compares open position margin. It reports mismatches without repairing them and exits nonzero on drift. PostgreSQL is the authoritative accounting store; SQLite numeric conversions are unsuitable for financial reconciliation.

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

The default API Worker has no route and is not deployed. The separate `landing` environment serves the approved landing and simulation frontend at [Workers.dev](https://open-alpha-arena-landing.l-elliottfuller.workers.dev/). Its public API returns a non-retryable 503 while required service bindings are absent. Admin remains unavailable and unknown API paths return 404. The [Worker guide](../deploy/worker/README.md) describes the environment boundary. The backend and proposed custom-domain route are not deployed.

For the Debian API, set `AUTH_MODE=access`, `ALLOWED_ORIGINS=["https://arena.leonfuller.com"]`, the Access issuer/audience/JWKS URL, `ADMIN_SUBJECTS`, and a private `ORIGIN_TRANSPORT_TOKEN`. Configure the Worker with the matching identity policy and its private Tunnel service credentials. Local login is unavailable in Access mode. Keep the origin token separate from visitor identity.

Use the [Worker guide](../deploy/worker/README.md) for exact variables and dry-run commands. Combined static assets and API handling follow [Cloudflare Workers Static Assets](https://developers.cloudflare.com/workers/static-assets/); visitor JWT validation follows [Cloudflare's validation guidance](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/). The Workers.dev frontend deployment is verified. Production API resources, DNS, and routing remain unconfigured.
