# Public API error handling validation

Run the browser acceptance fixture from the repository root:

```sh
CHROME_DEVTOOLS_AXI_SESSION=arena-error-validation-20261016 node scripts/error-handling-validation.mjs
```

The runner starts an isolated in-memory HTTP fixture and a temporary Vite proxy, uses Chrome DevTools AXI, and writes its result to [the validation evidence](evidence/error-handling-validation-2026-10-16.json). It does not use the replay database or call paid providers. The fixtures contain no financial rows.

The browser checks cover safe 500/502/503 messages, persistent missing-service configuration, HTML and malformed/empty 5xx bodies, a misleading JSON content type, malformed JSON success responses, rate-limit messaging and Retry-After focus cooldown, a failed upstream connection through Vite, scoped 404 handling, mobile overflow, healthy empty data, stale cached empty data, and manual recovery after failed queries. Screenshots are [desktop](screenshots/arena-api-error-500-desktop.png) and [mobile](screenshots/arena-api-error-500-mobile.png).

The network-drop case closes the local fixture socket; Vite turns that upstream disconnect into an HTTP proxy failure before the browser receives it. Worker tests exercise thrown upstream network errors directly. Validation also passed 18 Worker tests, 3 FastAPI boundary tests, Ruff, and full mypy. FastAPI's standard 422 response remains an array-shaped `detail` value to preserve the existing validation contract. A missing limiter/origin configuration stays non-retryable automatically and uses the visitor-facing “not connected yet” copy; runtime service errors remain retryable with temporary-unavailability copy.
