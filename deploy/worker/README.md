# Edge Worker

The Worker serves Vite assets from `dist/web`, applies the anchored public API allowlist, and protects `/admin`, `/admin-assets/*`, and explicit admin API routes with Cloudflare Access JWT verification. Its API origin is fixed in code at `https://arena-origin.leonfuller.com`.

The default `open-alpha-arena-edge` Worker remains disabled: it has no route, Workers.dev hostname, preview URL, or account-owned rate-limit namespace. The named `landing` environment deploys only the frontend as `open-alpha-arena-landing` on Workers.dev. It has no backend secrets, Access configuration, or rate-limit binding. Therefore public API requests fail closed with `503`, admin pages/APIs remain unavailable with `403`, and unknown API paths return `404`. Even if Access is configured later, API forwarding remains unavailable until a reviewed rate-limit binding and backend secrets are added.

Build and verify before a release:

```sh
npm ci
npm run build
npm ci --prefix deploy/worker
npm --prefix deploy/worker run typecheck
npm --prefix deploy/worker test
npm --prefix deploy/worker run verify:assets
```

`verify:assets` starts the real Wrangler local runtime with the built `dist/web` directory, then checks that `/simulation` and nested simulation URLs return HTML directly without a redirect, `/` remains available, admin access fails closed, unknown API paths return `404`, and public API calls fail closed with `503` when no rate limiter is configured.

After release review, deploy only the frontend environment with:

```sh
cd deploy/worker
npx wrangler deploy --env landing
```

This publishes the frontend to the Worker’s Workers.dev hostname only. It does not publish or enable the API, provision rate limiting, configure an Access application, or expose admin functionality. Do not enable the default Worker until its route, Access policy, origin secrets, and account-owned rate-limit namespace have a separate reviewed configuration.

The Worker config intentionally contains no origin or Access service secrets. If a later reviewed environment needs origin proxying, configure `ARENA_ORIGIN_TOKEN`, `CF_ACCESS_CLIENT_ID`, and `CF_ACCESS_CLIENT_SECRET` as Wrangler secrets. Set `ACCESS_ISSUER`, `ACCESS_AUDIENCE`, and the exact comma-separated `ADMIN_SUBJECTS` as non-secret variables.

`style-src 'unsafe-inline'` is limited to CSS declarations because the landing and simulation interfaces use React style properties for measured canvas dimensions, tile positions, and labels. Scripts remain restricted to same-origin files; no inline script allowance is present.
