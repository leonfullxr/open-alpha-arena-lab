# Validation results

This record distinguishes primary checks from delegate reports. Production has not been deployed; final acceptance remains in [implementation status](implementation-status.md).

## Primary platform checks

At `0aa4618`, a fresh migrated PostgreSQL database passed the complete backend suite: 76 tests. The funding checkpoint `2733cf0` passed 104 tests in an isolated checkout against another fresh migrated database. Ruff, strict source mypy, web type checking/build and fourteen Worker tests passed at that checkpoint. Later execution-evidence and collector changes need their final combined run.

The primary collected a trusted six-symbol Hyperliquid snapshot and approximately 25,900 candles. A second collection exposed an append-only candle update bug; that restart path is being corrected. Actual hourly BTC funding records had 54 ms and 6 ms offsets after the hour, which informed the bounded five-second matching policy. No genuine model call has been sent yet.

Both production npm audits returned zero findings. The Python audit found one development-only pytest advisory, duplicated by the advisory feed. The constraint was raised to `>=9.0.3,<10`, the lock resolved pytest 9.1.1, and the repeat installed-package audit returned no known vulnerabilities. These are dated dependency checks, not a guarantee against unknown vulnerabilities.

## Finance and authentication mutations

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

Read-only Muse reviews covered infrastructure, landing, frontend, the platform and funding checkpoints. The platform review found the multi-agent creation rejection, protective-exit account projection loss and incorrect benchmark fee key; all were corrected. Its funding review at `2733cf0` found no further medium-or-higher issue in its scope. Primary runtime verification subsequently found migration/collector paths absent from that source-only verdict; a review verdict does not replace executable checks.

The runtime implementer reports a twenty-round, two-agent PostgreSQL run using actual Alembic migrations, exact reconciliation and an accelerated schema-local database clock. A subprocess reconnects after round ten. Separate cases cover crash rollback, competing executors and expired fences. The primary must rerun this final checkpoint before acceptance. SQLite numeric storage is excluded from authoritative reconciliation evidence.

[Landing validation](landing-validation.md) records all five requested viewport captures, connected motion, resize, reduced motion, canvas failure and the observed loading budget. Primary preliminary simulation checks passed chart selection, series toggling, keyboard tooltips, pagination, model navigation, mobile overflow fixes and browser-side artifact hashes. Final v3 replay, funding, admin and live-mode browser checks remain pending.

The metadata service processed nineteen original prose/screenshot artifacts. It reported no AI provenance or invisible Unicode. Eight WebP screenshots lost ICC profile metadata; no pixel removal or statistical watermark detection was performed. Prose edits use plain language; no claim of human authorship or undetectability follows from these checks.
