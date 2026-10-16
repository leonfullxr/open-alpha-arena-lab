# Expanded simulation validation

The expanded browser pass completed with **57 checks passed and 0 failed** on 2026-10-16. It used the read-only local `DEMO REPLAY` run `036d6115-3edb-5dca-92d3-eb46a649a1b2` (Atlas and Vector, 40 decisions, 8 Atlas fills, 0 open Atlas positions). The browser runner records each check and its observed values in [the validation evidence](evidence/expanded-simulation-validation-2026-10-16.json). [Coordinator review evidence](evidence/expanded-simulation-coordinator-review-2026-10-16.json) separately records `npm run check`, Worker asset verification, protected-path checks, and final layout measurements.

Run against the local preview and API with the nine supplied reference images available at the original read-only directory:

```sh
SIMULATION_REFERENCE_DIR='/home/leon/Nextcloud/ETSIIT/ETSHIT/Github/open-alpha-arena-lab/logos/site' \
SIMULATION_API_BASE_URL=http://127.0.0.1:8026/api/v1/public \
SIMULATION_BASE_URL=http://127.0.0.1:5186 \
CHROME_DEVTOOLS_AXI_SESSION=arena-lab-expanded-tests \
node scripts/expanded-simulation-validation.mjs
```

The runner writes only its named evidence and screenshot artifacts. It uses a separate Chrome DevTools AXI session and does not modify replay records. The source images are read to record SHA-256 and byte length; they are not copied or edited.

## Reference comparison

Each supplied image was inspected and mapped to the closest implemented state. Local public records do not include the former hosted season aggregate or every source metric, so the table records the actual adaptation rather than implying exact data parity.

| Source image | Implemented state | Captured comparison and adaptation |
| --- | --- | --- |
| `09-40-50` | Aggregate chat, all models | [Screenshot](screenshots/expanded-simulation-aggregate-chat-1920x1080.png). Scoped to the actual baseline replay because the local API does not provide the former hosted season aggregate. |
| `10-36-42` | Aggregate chat filtered to Atlas | [Screenshot](screenshots/expanded-simulation-aggregate-chat-model-1920x1080.png). Uses the baseline's real Atlas account and decisions. |
| `10-36-49` | Selected-run chat rail | [Screenshot](screenshots/expanded-simulation-selected-chat-1920x1080.png). Uses actual public decisions and disclosed prompt/proposal artifacts. |
| `10-36-55` | Overall leaderboard | [Screenshot](screenshots/expanded-simulation-leaderboard-overall-1920x1080.png). Shows the public leaderboard rows for the baseline. |
| `10-36-58` | Advanced analytics | [Screenshot](screenshots/expanded-simulation-leaderboard-advanced-1920x1080.png). Fields absent from public records remain N/A. |
| `10-37-03` | Average enabled with advanced analytics | [Screenshot](screenshots/expanded-simulation-leaderboard-average-summary-1920x1080.png). Atlas and Vector are separate groups, each N=1, so the screenshot cannot demonstrate a real multi-account provider/model average. A synthetic helper check covers that arithmetic separately. |
| `10-37-12` | Atlas model summary | [Screenshot](screenshots/expanded-simulation-model-summary-1920x1080.png). Uses the public profile and recorded metrics. |
| `10-37-15` | Atlas positions and fills | [Screenshot](screenshots/expanded-simulation-model-positions-trades-1920x1080.png). The replay has no open positions; its eight actual fills are shown. |
| `10-37-25` | Season details rail | [Screenshot](screenshots/expanded-simulation-season-details-1920x1080.png). Adapted to the local public run index and declared run profiles. |

Three additional mobile captures cover live chat, the leaderboard, and the model page: [live](screenshots/expanded-simulation-live-mobile-390x844.png), [leaderboard](screenshots/expanded-simulation-leaderboard-mobile-390x844.png), and [model](screenshots/expanded-simulation-model-mobile-390x844.png).

## Behavioral coverage and data limits

A follow-up pass also verifies N=1 average labels omit the competition suffix, overall and advanced tables fit their desktop container with 11 and 13 columns, and the average-mode advanced table scrolls locally on phones. The browser checks cover the protected landing route and loaded fonts; live navigation and rail layout; leaderboard widths, local table scrolling, sticky headers, default equity ordering, sort reversal, winner identity, keyboard tab navigation, and competition switching; chat model/symbol filters, empty state, pagination, public `USER_PROMPT` and `TRADING_DECISIONS` disclosure, and prompt download SHA-256; model route errors, public settings/hash disclosure, chart range selection, and newest-first fills with side colors. Responsive route checks use widths 1920, 1440, 1024, 768, 640, and 390 pixels. At 1920 the live rail measures 500 px; it stacks below the article at widths up to 800 px. The leaderboard reaches its 1568 px maximum at 1920, and its table scrolls within its container on narrower screens.

The real baseline has zero open positions. To exercise the position card and responsive card grid without inventing paper results or changing the database, the runner mounts the exported component with an explicitly labeled, browser-only synthetic fixture. It checks exit-plan fields and unavailable values, then observes 3/2/1 columns at 768+/640/390 px. This fixture is not presented as replay evidence.

The public records do not expose biggest win/loss or holding time journals, cash, per-position leverage, liquidation price, or per-position unrealized P&L. Unpaired fills also do not support reliable per-trade entry/exit pairs, notionals, holding time, or net P&L. Those fields remain unavailable rather than inferred. The model page discloses its metric definitions: Total P&L is account equity minus competition starting capital; net realized is realized P&L less cumulative fees and excludes funding; confidence is the mean of recorded proposal confidence values in up to the first 100 decisions (this replay has 20). The replay's public metrics endpoint has no average-leverage value.

When average is enabled, rows group by exact provider and model. Each numeric metric is the arithmetic mean of finite, non-null member values; unavailable values do not enter that metric's divisor. Group count includes all member accounts. Total P&L is calculated for each account as equity minus starting balance, then averaged; win rate and Sharpe are arithmetic means and are not pooled statistics. A two-account browser call to the exported pure helper checked equity 100/200 → 150, ROI 1/3 → 2, fees 2/null → 2 (null excluded), and null Sharpe exclusion. It does not change published leaderboard data.

The final screenshot files show current app captures at 1920×1080 for the nine source mappings and 390×844 for the three responsive routes. The evidence JSON contains source-image hashes, per-check results, viewport measurements, and actual replay values. `npm run check` and Worker asset verification are documented in the coordinator review artifact; they are separate from the 57 browser checks.
