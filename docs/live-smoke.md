# Genuine provider smoke, 2026-10-15

The bounded live paper run finished five rounds with two models: `opencode_go/mimo-v2.6-flash` and `opencode_go/glm-5.3-flash`. All ten requests returned HTTP 429. Successful genuine decisions and executed-fill acceptance remain pending.

The [finished-run export and ten request artifacts](evidence/provider-smoke-2026-10-15.json) were captured through explicit public API schemas. Every request hash was verified again while archiving.

Competition: `4e755cb8-d583-4adf-aad4-6e456d98d166`. Logical decision times ran from 12:02:29 UTC through 12:14:29 UTC at the frozen 180-second cadence, with a 120-second response deadline. Each round used one persisted canonical Hyperliquid snapshot for both independently funded $10,000 paper accounts. A separate ordinary collector kept quotes and funding evidence current.

Ten retained reservations total **$0.518984**, below the configured **$2.50** competition cap. These are conservative internal reservations, not a provider invoice. The provider reported no token usage or actual cost. The platform records the HTTP status without assuming the reason for the rejection or whether anything was billed.

Each invocation ended as `PROVIDER_ERROR` / `PROVIDER_HTTP_ERROR`. There were no proposals, orders, fills or trade journals. Both accounts reconciled exactly. Execution quote pins remain null because no accepted provider output reached execution. No replacement fixture, retry of the same dispatch or paid provider fallback was used.

Request artifacts preserve the exact nonsecret HTTP body supplied to the provider client, including the actual system/user prompts, model and settings. The first request was 48,894 bytes and its advertised SHA-256 matched an independent browser calculation. Provider credentials stayed in process memory and transport headers stayed outside public evidence. The adapter used the project's own user agent and a stable conversation identifier.

This run froze the historical version-1 prompt. Browser inspection found that it listed an action absent from the current schema. Future smoke competitions use the corrected `baseline-v2.md`; the run's original bytes remain unchanged. No model output was returned in this run, so the correction is not presented as a successful model result.

Default startup remains the offline demo. Another genuine run requires an explicit operator action and usable provider access; this result does not establish live-model acceptance or production readiness.
