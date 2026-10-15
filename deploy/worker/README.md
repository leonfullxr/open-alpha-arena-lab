# Edge Worker

The Worker serves Vite assets from `dist/web`, applies the anchored public API allowlist, and protects `/admin`, `/admin-assets/*`, and the explicit admin API routes with Cloudflare Access JWT verification. Its origin is fixed in code at `https://arena-origin.leonfuller.com`. It forwards a verified admin JWT only in `X-Arena-User-JWT`; `X-Arena-Origin-Token` and the Cloudflare Access service token authenticate transport to the origin independently.

The checked-in Wrangler config has no route, custom domain, Workers subdomain, or preview URL enabled. It also has no rate-limit namespace because that identifier belongs to the target account. API requests fail closed with `503` until an account-owned `ARENA_RATE_LIMITER` binding exists. Before enabling an entry point, add a Wrangler `ratelimits` binding named `ARENA_RATE_LIMITER` with a positive integer namespace unique to the account and a reviewed `simple` limit and period. Do not deploy a placeholder namespace.

Set `ACCESS_ISSUER`, `ACCESS_AUDIENCE`, and the comma-separated exact `ADMIN_SUBJECTS` list as non-secret Worker variables. Add these secret bindings through Wrangler's secret interface:

```sh
npx wrangler secret put ARENA_ORIGIN_TOKEN
npx wrangler secret put CF_ACCESS_CLIENT_ID
npx wrangler secret put CF_ACCESS_CLIENT_SECRET
```

The deploy command is deliberately absent from the workflow. Local review uses `npm run deploy:dry-run` after the frontend build. Remote deployment, route enablement, Access application configuration, origin tunnel checks, and account-bound rate-limit provisioning require a separate release review.

`style-src 'unsafe-inline'` is limited to CSS declarations because the landing and simulation interfaces use React style properties for measured canvas dimensions, tile positions, and labels. Scripts remain restricted to same-origin files; no inline script allowance is present.
