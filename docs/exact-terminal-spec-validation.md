# Exact terminal simulation validation

The browser validation completed on 2026-10-16. The exact-spec pass recorded **25 checks passed and 0 failed**. The refreshed behavior pass recorded **57 checks passed and 0 failed**. Machine-readable results are in [exact-spec evidence](evidence/exact-terminal-spec-validation-2026-10-16.json) and [behavior evidence](evidence/exact-expanded-simulation-validation-2026-10-16.json).

Both passes used the read-only finished replay `036d6115-3edb-5dca-92d3-eb46a649a1b2` with Atlas and Vector. The API returned 40 decisions and 8 Atlas fills. Atlas has no open positions. The API also returned four preexisting lifecycle fixtures, each labeled `TEST FIXTURE` in the run band. This validation pass did not create or change database records.

At 1920 px, the navigation row measures 58 px, the run band 45 px, and the context row 32 px at y=103. The article measures 672 px and the activity rail 500 px. At 1440 px the page has no horizontal overflow and the context and rail start at y=103. At 390 px the navigation row remains 58 px, the page stays 390 px wide, and all five navigation links remain inside the navigation strip. The rail stacks below the article on mobile.

The exact pass checked the live and aggregate rail labels, API-backed run links and ticker symbols, BLOG's `/#methodology` target, the paper, secondary, panel, ink, muted, divider, link, positive, and negative tokens, and loaded IBM Plex Mono fonts. It expanded a real decision card and found its public prompt, recorded proposals, and download control. The behavior pass verified that the prompt download bytes match the published SHA-256.

The model page measures 1216 px wide at desktop size. Its P&L strip is 90 px high with three columns, and the Atlas page shows the eight real fills available in this replay. The named palette maps eight model names consistently across account order; Atlas and Vector use the first two fallback slots. The leaderboard measures 1568 px wide at x=176, uses a 35 px heading and 22 px rows, sorts by account value by default, and keeps the 58 px shared header sticky. The standalone captures use the static grain background.

The exact browser captures include [the live index](screenshots/exact-terminal-live-1920x1080.png), [the leaderboard](screenshots/exact-terminal-leaderboard-1920x1080.png), and [the Atlas model page](screenshots/exact-terminal-model-1920x1080.png). The behavior pass also saved the nine reference-state captures and mobile route captures with the `exact-expanded-simulation-` prefix.

Run the exact pass with the local preview and API on ports 5186 and 8026:

```sh
CHROME_DEVTOOLS_AXI_SESSION=arena-exact-spec-tests \
node scripts/exact-terminal-spec-validation.mjs
```

Run the 57-check behavior pass with the supplied reference images in the original checkout:

```sh
SIMULATION_REFERENCE_DIR='/home/leon/Nextcloud/ETSIIT/ETSHIT/Github/open-alpha-arena-lab/logos/site' \
SIMULATION_EVIDENCE_FILE=docs/evidence/exact-expanded-simulation-validation-2026-10-16.json \
SIMULATION_ARTIFACT_PREFIX=exact-expanded-simulation \
CHROME_DEVTOOLS_AXI_SESSION=arena-exact-spec-expanded \
node scripts/expanded-simulation-validation.mjs
```

The runners read public API records and write only their evidence and screenshot files. They do not seed or modify the database. They stop only their named browser sessions.
