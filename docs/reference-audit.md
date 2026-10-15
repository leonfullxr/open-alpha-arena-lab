# Reference and license audit

Inspected 2026-10-15. Original implementation only: no source code, prompts, logos, captured datasets or proprietary font files from these projects are redistributed. The local PDF is an untracked reference and is not part of the MIT distribution. Repository metadata and displayed source trees were checked through GitHub; README feature claims below are not runtime verification. GitHub's unauthenticated REST rate limit prevented that path; authenticated GraphQL supplied default-branch revisions.

| Reference | Revision / license evidence | Scope visible / completeness limit | Reuse / replacement and risk |
| --- | --- | --- | --- |
| [wquguru/nof0](https://github.com/wquguru/nof0) | main fe40d850; README claims MIT, detected license null | Next web and Go backend source trees; README itself reports partial backend | Visual study only; ambiguous license, no code imported |
| [etrobot/open-alpha-arena](https://github.com/etrobot/open-alpha-arena) | main 15d47c1d; README claims MIT, detected license null | Python/SQLite and CCXT paper app advertised; not executed here | Architectural reference only; replace persistence and accounting |
| [HammerGPT/Hyper-Alpha-Arena](https://github.com/HammerGPT/Hyper-Alpha-Arena) | main 9bdf62de; Apache-2.0 detected | Backend/frontend, Hyperliquid/Binance integration advertised; not executed | No source imported; live execution would exceed our paper scope |
| [NoFxAiOS/nofx](https://github.com/NoFxAiOS/nofx) | dev d6d689f3; AGPL-3.0 detected | Multi-venue terminal architecture; not executed | Explicitly excluded from implementation |
| [yufenng/Open-Nof1-AlphaArena](https://github.com/yufenng/Open-Nof1-AlphaArena) | main 8ac745e6; MIT detected | README explicitly says static mocks with no backend | Information hierarchy reference only; replace data and branding |
| [SnowingFox/open-nof1.ai](https://github.com/SnowingFox/open-nof1.ai) | master 39226a68; README claims MIT, detected license null | Single-model real-market app advertised; not executed | No reuse; account isolation and execution need our own contracts |
| [sunshinfight/nof1-arena-data](https://github.com/sunshinfight/nof1-arena-data) | main 00f2196b; README claims MIT, detected license null | Historical SQLite capture; documented incomplete trade history | No dataset imported; source license would not establish data rights |
| [kukapay/awesome-alpha-arena](https://github.com/kukapay/awesome-alpha-arena) | main a5f4c5f0; MIT detected | Curated directory, not an engine | Discovery only |
| [Nof1](https://www.nof1.ai/) / [Alpha Arena](https://alphaarena.ai/) | Proprietary/reference only | Local PDF is measured homepage evidence; simulation internals not verified | Original branding, geometry, assets and prompts |
| [Newsreader](https://github.com/google/fonts/tree/main/ofl/newsreader) | SIL Open Font License 1.1 | Variable TTF converted to Latin WOFF2 subset with fonttools | Self-hosted font, bundled OFL; no Signifier distribution |

Unverified: runtime quality, current branch internals beyond displayed trees, third-party asset rights, and parity with the closed original engine. No dependency on a reference project's code is needed.

Primary integration references: [Hyperliquid info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [Workers Static Assets](https://developers.cloudflare.com/workers/static-assets/), [Cloudflare Access JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/). These establish API contracts, not deployment success.
