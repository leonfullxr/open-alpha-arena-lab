# Validation results

This is a work record, not a production certification. The implementation remains under review; see [status](implementation-status.md). The primary ran the checks below, independently of implementer reports.

## Worker guard mutations

All 13 deliberate wrong implementations were rejected by behavioral tests. Source files were restored byte for byte after every mutation. The first sweep exposed three missing JWT cases; signed-token tests were added before the final sweep. A redundant manual check was removed so required-claim enforcement has one owner in JOSE.

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

Independent Worker type checking and 10 behavioral tests passed. An independent read-only Muse review found no medium-or-higher infrastructure bug at that checkpoint. Its low notes concerned static-header coverage, JWKS cache lifetime and POST-body coverage. The latter two remain subject to final integration review.

## Accounting checkpoint mutations

The first pure accounting sweep killed 11 of 16 mutations. Five survivors were sent back for stronger tests or removal of redundant guards. This table records that initial result; it does not claim the final financial gate has passed.

| Guard deliberately broken | Initial result |
| --- | --- |
| Opening executable side | Killed |
| Close PnL uses slipped fill | Killed |
| Commission charged | Killed |
| Funding direction | Killed |
| Maximum order notional | Killed |
| Maximum leverage | Survived — test requested |
| Available collateral | Survived — test requested |
| Gross exposure | Survived — test requested |
| First pyramiding check | Survived — a second guard also rejects; simplify |
| Instrument quantity step | Killed |
| Stop side | Killed |
| Remaining held-position marks on close | Survived — test requested |
| Duplicate quote rejection | Killed |
| Future quote rejection | Killed |
| Quote-set skew | Killed |
| Detached input account | Killed |

The independently executed PostgreSQL core suite passed 16 tests across finance, durable replay, append-only evidence, balanced journals, invocation fencing, public schemas and local session authentication. Alembic reported no model drift at that checkpoint. A separate read-only Muse review confirmed a medium bug in multi-position protective exits; the fix and broader risk policy are in progress.

## Frontend

[Landing validation](landing-validation.md) includes five viewport captures, motion and failure-state checks, observed performance and limits. Preliminary simulation checks passed chart selection, series toggling, keyboard tooltips, 40-record pagination and browser-side SHA-256 verification of both exact artifact byte downloads. Final simulation and admin regression checks are pending integration.
