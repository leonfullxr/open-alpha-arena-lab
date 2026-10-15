# Security boundaries

This document records the required boundaries and validation targets. Implementation status and actual completed checks are in [implementation-status.md](implementation-status.md).

Public routes under `/api/v1/public/` are read-only and expose explicit schemas. Administrative changes use `/api/v1/admin/`; public and admin OpenAPI documents and generated contracts are separate. Paginated queries, exports and SSE have bounds. The proxy permits only reviewed methods and paths to a fixed HTTPS origin, strips internal and transport headers supplied by visitors, and never buffers SSE.

Local mode uses Argon2id password verification, server-side expiring sessions and opaque cookie tokens stored only as hashes. Bootstrap is an interactive CLI operation with no default password. Cookie mutations require an allowed Origin and use HttpOnly/SameSite cookies. Development HTTP cookies and production HTTPS cookies must be configured distinctly. Session auth is unavailable in Access mode.

Access mode requires signature, issuer, audience, expiration and an allowlisted nonempty subject at both Worker and API. The original visitor token travels under `X-Arena-User-JWT`, independently of the origin service token and the Tunnel's own assertion. A transport token alone grants no admin rights. Admin HTML and its asset paths must be protected. Alternate production entrypoints are disabled. Preview environments must use fixtures or isolated staging data and separate Access policies.

Provider credentials are server-side environment references. Public model metadata contains the model identifier and reproducibility settings, never provider keys, arbitrary headers or internal exception bodies. No provider key belongs in Vite variables, browser storage or public artifacts. URLs are configured through a trusted server allowlist; redirects and arbitrary endpoints must not enable SSRF. Paid calls require explicit model selection and a reserved bounded budget. Uncertain calls are not automatically retried.

Only public-safe inputs can reach prompt rendering. Exact sent prompt bytes, hashes, visible returned decisions, justifications and risk outcomes are evidence. Hidden provider reasoning, personal information and secrets are excluded by construction. Frontend rendering uses text nodes, and exports must avoid spreadsheet formula execution. Secret-canary and schema tests guard these boundaries.

All trading is virtual. No wallet, exchange trading key, real-order adapter or live-money arming path exists. The local database and API bind to loopback; Tailscale remains the administration/recovery channel. Backups contain sensitive account/operator metadata and must be handled as private data.
