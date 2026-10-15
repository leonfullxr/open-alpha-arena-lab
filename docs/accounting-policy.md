# Paper accounting policy

All accounts are virtual linear perpetual accounts. Decimal values are authoritative; browser floating-point conversions are for display and chart coordinates only. Each run publishes its frozen rules and model settings. The baseline uses common snapshots and rules with independent accounts; extended runs disclose their changes separately.

Opening longs pay the ask and opening shorts receive the bid. Closing a long receives the bid; closing a short pays the ask. Configured slippage moves the fill against the account. Fees use filled notional. Initial margin is reserved collateral and remains part of equity; it is not a second expense. Equity is cash plus marked unrealized PnL. Realized close PnL uses the actual slipped fill price.

Stops and take profits trigger on trusted mark prices and execute at available executable quotes. A gap can therefore produce a worse fill than the trigger. Estimated liquidation is a paper risk policy, not a reproduction of the venue's liquidation engine. The implementation status records whether its persistent runtime path has passed validation.

Positive funding rates make longs pay and shorts receive; negative rates reverse the transfer. Live paper funding uses the actual hourly Hyperliquid `fundingHistory` rate, without dividing it again. Notional uses quantity times an oracle price captured within ten seconds before the boundary. This is a disclosed paper approximation: it does not reproduce a venue account's exact boundary position or oracle value. Predicted context rates never become settled payments.

Funding evidence preserves the source event time, including milliseconds. Public API observations on 2026-10-15 returned hourly BTC records at 10:00:00.054 UTC and 11:00:00.006 UTC. Matching allows a bounded five-second offset after the UTC hour; the source time remains visible. One shared boundary task pins the oracle evidence. Missing rates are retried for at most thirty minutes. Missing oracle evidence or an expired rate deadline produces a `SKIPPED` receipt with a reason and a null amount, rather than a fictitious zero payment.

Position lifecycles retain immutable quantity and entry basis. A position held at the boundary remains eligible if it closes before delayed settlement. Pausing a competition does not stop funding on its held positions. A unique position/boundary receipt prevents duplicate accounting after restart. Safe canonical rate records have their own downloadable bytes and hashes; transport responses and unknown extra fields are not published. The deterministic offline replay discloses zero fixture funding and makes no market requests.

The BTC comparison uses the same starting capital, the first recorded ask and the final recorded bid, adverse slippage and both transaction fees. Its return is unlevered. A missing trustworthy price series produces an unavailable benchmark, not a fabricated line. Win rate and profit factor use documented closed-trade outcomes; a zero denominator produces an unavailable value. A per-round Sharpe value is not an annualized estimate.

Durable fills, position changes, account changes, balanced postings, execution results and public events belong to one transaction. Database uniqueness and worker fences prevent repeated application. External inference cannot be guaranteed exactly once: an uncertain dispatch is retained and not automatically repeated.

See [implementation status](implementation-status.md) for actual checks and limitations. Venue funding semantics are documented by [Hyperliquid](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding); our paper policies and estimates remain our own choices.
