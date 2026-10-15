# Architecture and fixed decisions

React, TypeScript and Vite provide separately loaded landing, simulation and admin entries. Original canvas/SVG artwork follows the measured layout in the local nine-page reference PDF. Newsreader is self-hosted under OFL. Landing has no API dependency. No third-party Alpha Arena source, brand assets or proprietary font files are copied.

FastAPI and PostgreSQL run on Debian with independent collector, scheduler and executor entrypoints. SQLAlchemy transactions, database uniqueness, row locks and worker fencing protect durable state. Decimal is authoritative for quantities, prices, fees, funding, collateral and PnL. Only paper execution exists.

Baseline `alpha_2025_baseline` uses BTC, ETH, SOL, BNB, DOGE and XRP; virtual initial capital $10,000 per account; 180-second rounds; T+120 response deadline; one canonical snapshot and a shared execution quote set. Execution quote age <=10 seconds and cross-symbol skew <=5 seconds. Incomplete quote sets block new baseline entries. Protective exits operate independently on trusted fresh prices. Multi-symbol proposals execute in frozen manifest order after account revalidation. Rules, prompts, provider model settings, universe and evidence schema freeze at start.

Market features follow the frozen `trailing_500_v1` policy: each fully warmed bar uses exactly 500 trailing completed bars. Receive timestamps and prior candle facts are immutable; batch and incremental ingestion produce the same quantized features. Cold backfill contains 511 bars so the published twelve-bar window is warmed.

`research_extended` has separate rankings for changed tools, strategies, assets, memory, collaboration or execution policies. Private weights are compatible with common baseline inputs/rules. Confidential strategies are deferred.

Inference dispatch is not exactly-once: uncertain dispatches are audited and never automatically repeated. Fills, balanced ledger postings, positions, durable events and outcomes commit atomically. Public evidence uses explicit safe schemas, not generic ORM serialization. Exact prompt bytes and SHA-256 hashes are retained; private credentials, headers, personal information and hidden provider reasoning never enter public artifacts.

Public API `/api/v1/public/*` is read-only, bounded and separately documented. Admin API `/api/v1/admin/*` requires authenticated RBAC and uses a separate OpenAPI document and frontend types. This intentionally refines the master brief's shared endpoint prefix.

Production path: browser -> Worker with Static Assets -> service-authenticated Cloudflare Tunnel -> Debian API. Fixed origin `https://arena-origin.leonfuller.com`; frontend target `arena.leonfuller.com`. Worker allowlists paths/methods, strips visitor internal headers, streams SSE, and validates admin Access JWT independently of backend RBAC. The origin transport token does not grant visitor admin rights. Local Argon2id sessions and production Access modes are mutually exclusive. Default offline demo makes no external requests.

Account/DNS/Tunnel/Access resources and production deployment remain unverified until a concrete build is reviewed. Tailscale remains the server recovery channel. No alternate public production entry points or production-connected previews.

## Transaction and identity refinements

Read-only Opus design review identified lock-upgrade deadlocks, late-committing sequence gaps and Tunnel identity substitution as implementation risks. Serialize short competition writes using one order: competition `FOR UPDATE`, job, account, then positions in stable order. The per-competition event counter advances inside the same transaction, so published sequence order follows commit order. Never keep a transaction open during an external model request.

Persist dispatch before network I/O, with a monotonic worker fence. An expired uncertain dispatch becomes an audited terminal `PROVIDER_ERROR` / `DISPATCH_UNCERTAIN` and is never automatically dispatched again. An undispatched job past its deadline is `PROVIDER_TIMEOUT` / `NOT_DISPATCHED`. Dispatch/input artifacts and response artifacts are separate append-only evidence. Application-level idempotency does not promise exactly-once provider billing.

The Worker validates the visitor's Access JWT and forwards that same signed value as `X-Arena-User-JWT`; it strips visitor-supplied copies first. The backend verifies signature, RS256, issuer, audience, exp/iat/sub and an explicit subject allowlist again. This is independent of the Tunnel service assertion, which may overwrite `Cf-Access-Jwt-Assertion`. A separate origin token authenticates transport only. No fallback between local and Access authentication modes.

Financial operations use a Decimal precision-60 context. Amounts are quantized to 18 fractional digits before ledger balancing and insertion, with numeric(38,18) overflow rejected. Exact snapshot/prompt bytes are hashed before storing; queryable JSON is not the evidence hash source.
