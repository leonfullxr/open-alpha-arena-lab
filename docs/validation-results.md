# Validation results

This record distinguishes primary checks from delegate reports. The approved landing and simulation frontend are live on the persistent Workers.dev host. The backend and proposed custom-domain route are not configured; the hosted public API returns a safe non-retryable 503. Current release evidence appears in the [session closeout](session-closeout-2026-10-16.md); the older counts below describe their original historical runs.

## Current merged release checks

The current release passed 20 deterministic browser checks for safe API failure copy, missing configuration, malformed and empty error bodies, 429 cooldowns, scoped 404 states, healthy empty data, stale data, manual recovery, and mobile layout. Separate HTTP and asset-hash checks verified seven routes and exact SHA-256 matches for 30 hosted assets. Browser checks at 1920 px desktop and 390 px mobile found no horizontal overflow. Manual retry requested failed data again, and the simulation displayed no fabricated rows.

The latest focused backend checks passed 18 Worker tests and 3 FastAPI boundary tests. Ruff, strict mypy over 56 files, and the frontend build passed. All three PR checks and the full main CI run passed. An independent browser replay preserved eight recorded paper fills through an injected 503 and manual recovery. That check made no provider calls and no real orders.

The hosted public endpoint currently returns `503` with `rate_limit_unavailable`, `retryable: false`, and the detail "The research data service is not connected yet." The admin route returns `403`; an unknown API route returns `404`. No backend bindings, secrets, Access resources, DNS, Tunnel, database, or provider configuration were deployed. See the [error handling validation guide](error-handling-validation.md), [branding validation](branding-validation-2026-10-16.md), and [session closeout](session-closeout-2026-10-16.md).

## Earlier primary platform checks

The primary ran the complete backend suite after the independent-review corrections against a fresh disposable PostgreSQL database migrated through all ten Alembic revisions: **128 passed**. Four additional provider-status negative parameters were then added; that focused suite passed all five cases. This includes the twenty-round/two-agent worker competition, a subprocess restart after round ten, exact ledger reconciliation, competing execution workers, stale fences, crash rollback, immutable evidence, safe public exports and authorization. Ruff, strict mypy over 56 implementation files, generated contracts, web type checking/build, fifteen Worker tests and Wrangler's deployment dry run passed. Alembic reported no schema drift. The remaining test warning comes from upstream Starlette/httpx compatibility; the Alembic path separator is now explicit.

A fresh real Hyperliquid collection stored 3,066 completed candles and a trusted six-symbol snapshot. A repeated collection appended a new snapshot without rewriting candles. The earlier immutable-update failure is fixed: completed candles are append-only, contradictory facts fail closed, catch-up uses bounded chunks, and feature windows use the frozen `trailing_500_v1` policy. A candle fetch or gap failure still publishes fresh trusted prices for protective exits, while new inference stops before an attempt or spend reservation. Actual hourly BTC funding records had 54 ms and 6 ms offsets after the hour, which informed the bounded five-second matching policy.

The genuine five-round/two-model smoke finished with ten terminal HTTP 429 responses. Its ten retained spend reservations total $0.518984, below the configured $2.50 cap; actual provider usage and billing were not reported. Both accounts reconcile exactly, with no fills or trade journals. Successful model and fill acceptance remain pending. The exact first 48,894-byte request artifact was independently SHA-256 verified in the browser. Archive checks verified all ten request hashes, the canonical snapshot hash inside each request, identical snapshots/prompts/logical times within each round, matching frozen-rules hashes and the body-size limit. Historical v1 requests remain unchanged; subsequent runs use the corrected version-2 prompt. No provider error body or transport header is published. The [public API archive](evidence/provider-smoke-2026-10-15.json) contains all ten byte-preserving request artifacts and the safe finished-run export; [the smoke record](live-smoke.md) explains its limits.

Both production npm audits returned zero findings. The Python audit found one development-only pytest advisory, duplicated by the advisory feed. The constraint was raised to `>=9.0.3,<10`, the lock resolved pytest 9.1.1, and the repeat installed-package audit returned no known vulnerabilities. These are dated dependency checks, not a guarantee against unknown vulnerabilities.

## Historical mutation checks

The primary ran each deliberate wrong implementation in an isolated checkout and restored source bytes after every run. The original required-claim mutation survived because tests supplied null claims instead of omitting them; signed-token omission tests now kill it. All eighteen mutations below are killed.

| Guard deliberately broken | Final result |
| --- | --- |
| Maximum leverage | Killed |
| Available collateral | Killed |
| Gross exposure | Killed |
| Daily loss limit | Killed |
| Drawdown limit | Killed |
| Close PnL uses slipped fill | Killed |
| Commission charged | Killed |
| Instrument quantity step | Killed |
| Duplicate quote rejection | Killed |
| Future quote rejection | Killed |
| Quote-set skew | Killed |
| Access JWT issuer | Killed |
| Access JWT audience | Killed |
| Access JWT required claims | Killed |
| Access JWT signature | Killed |
| Admin subject allowlist | Killed |
| Origin transport token | Killed |
| CSRF origin check | Killed |

## Funding mutations

The first funding sweep killed eight of thirteen mutations. New first-insert and invalid-oracle cases closed five gaps; the primary reran all thirteen successfully against PostgreSQL. Tests check rejection before any rate evidence exists, so duplicate-record checks do not mask validation failures.

| Guard deliberately broken | Final result |
| --- | --- |
| Oracle captured before boundary | Killed |
| Oracle age at most ten seconds | Killed |
| Trusted oracle source | Killed |
| First rate matches downloaded record | Killed |
| Funding source timestamp offset bound | Killed |
| Public-safe rate projection | Killed |
| Exact funding artifact hash | Killed |
| First rate arrives before deadline | Killed |
| Funding idempotence | Killed |
| Closed-after-boundary position eligibility | Killed |
| Skipped payment has null amount | Killed |
| Hourly rate is not divided again | Killed |
| Funding payment sign | Killed |

## Review remediation mutations

The primary killed all seven additional mutations after the final review. One initial fault injection exposed a test session left open after a failed assertion; cleanup now closes it in `finally`, and the repeated mutation sweep finished with assertion failures rather than timeouts. Source bytes were restored after every run.

| Guard deliberately broken | Final result |
| --- | --- |
| Accepted response survives inference lease expiry | Killed |
| Reconciliation precedes inline protective effects | Killed |
| Tiny journal imbalance is reported exactly | Killed |
| Malformed candle is normalized at the HTTP boundary | Killed |
| Published HTTP status is an integer | Killed |
| Published HTTP status stays within 100–599 | Killed |
| Published HTTP status preserves the recorded value | Killed |

## Worker proxy mutations

All thirteen deliberate wrong implementations were killed. The first sweep exposed missing JWT cases, which were added before the final pass. JOSE owns required-claim validation; its redundant manual check was removed.

| Guard deliberately broken | Final result |
| --- | --- |
| Public path allowlist | Killed |
| Public read-only methods | Killed |
| Visitor credential stripping | Killed |
| Fixed upstream origin | Killed |
| Missing rate-limit binding fails closed | Killed |
| Admin subject allowlist | Killed |
| JWT audience | Killed |
| JWT issuer | Killed |
| JWT required claims | Killed |
| SSE body streamed directly | Killed |
| SSE no-cache policy | Killed |
| Upstream redirects suppressed | Killed |
| Raw upstream server errors suppressed | Killed |

## Independent review and runtime evidence

Read-only Muse reviews covered infrastructure, landing, frontend, the platform and funding checkpoints. The platform review found the multi-agent creation rejection, protective-exit account projection loss and incorrect benchmark fee key; all were corrected. Its funding review at `2733cf0` found no further medium-or-higher issue in its scope. Primary runtime verification subsequently found migration/collector paths absent from that source-only verdict; a review verdict does not replace executable checks. The final Opus fallback review found an expired inference lease incorrectly blocking accepted execution, a malformed-candle exception skipping fresh prices, inline protection preceding reconciliation, and a leftover SQLite journal tolerance. Each was corrected with a behavioral regression. Twelve accepted responses now progress after lease expiry and a database reconnect; wrong fences and late inference remain rejected. Ledger comparison runs before inline protection, and all dialects require exact journal balance.

A read-only Opus follow-up at `0256f55` found no confirmed medium-or-higher product defect. Its remaining clock-flake note was corrected by sharing the existing fixture deadline; the four recovery cases passed again. The review loop stopped on that verdict, with primary checks retained.

The primary reran the final PostgreSQL worker proof through real Alembic migrations. Its schema-local database clock advances through the frozen 180-second cadence; deadlines stay immutable. SQLite numeric storage is excluded from authoritative reconciliation evidence.

[Landing validation](landing-validation.md) records all five requested viewport captures, connected motion, resize, reduced motion, canvas failure and the observed loading budget. Browser checks on the v3 replay confirmed fill-to-decision linkage, exact rules hashes, position lifecycle facts and the funding-history empty state. The admin browser created a provider reference, prompt version and draft competition, then rejected start with a missing credential and checked configuration without contacting a provider. Long names and SHA-256 feedback exposed a mobile grid overflow; the corrected page measures 390 px at a 390 px viewport. The genuine live dashboard connected its event stream, displayed current market quotes and exposed the real provider failures. On a separate, explicitly labeled UI fixture, admin pause/resume/finish buttons updated both the ticker and competition state without reload. The shell and body share the same competition query. Sign-out returned protected API requests to HTTP 401. The genuine competition was not altered by these UI fixture transitions.

## Final boundary mutations

In an isolated checkout of `3fbba44`, all ten deliberate changes below failed their behavioral PostgreSQL or runtime tests. The unchanged focused suite passed five tests; each source file was restored byte for byte. These supplement the finance, authentication, funding and Worker mutations above.

| Guard deliberately broken | Final result |
| --- | --- |
| Export transaction is read-only | Killed |
| Export uses a repeatable snapshot during a concurrent write | Killed |
| Unknown rules fields withhold exact raw bytes | Killed |
| Round quote pin cannot change after first assignment | Killed |
| Round's other evidence columns remain immutable | Killed |
| Candle catch-up fetch stays bounded | Killed |
| Stale candle windows block inference | Killed |
| Candle failure retains fresh protective prices | Killed |
| Live input requires complete warmed evidence | Killed |
| Smoke account insertion follows its agent flush | Killed |

The metadata service processed nineteen original prose/screenshot artifacts and three final screenshots. It reported no AI provenance or invisible Unicode. Eight WebP screenshots lost ICC profile metadata; no pixel removal or statistical watermark detection was performed. Prose edits use plain language; no claim of human authorship or undetectability follows from these checks.
