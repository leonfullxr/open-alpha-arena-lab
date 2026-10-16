# Simulation validation

The simulation UI passed 63 API and browser checks against a real local replay. The suite exercised the run index, selected competition, leaderboard, and model profile; verified artifact downloads against API SHA-256 values; and covered filters, pagination, keyboard tabs, chart ranges and series, empty/lifecycle states, and rules verification errors. Desktop, tablet, and mobile captures were taken at six viewport sizes for both selected-run routes.

The baseline is competition `036d6115-3edb-5dca-92d3-eb46a649a1b2`, a 20-round `alpha_2025_baseline` replay labeled `DEMO REPLAY · fill evidence v3 · deterministic local fixtures`. It contains 40 decisions, 16 fills, 42 equity rows, and two model accounts. Optional lifecycle records are visibly labeled `TEST FIXTURE`; the running and paused fixtures were never dispatched. No provider calls were made.

The machine-readable results are in [browser validation evidence](evidence/simulation-browser-validation-2026-10-16.json) and [API outage recovery evidence](evidence/simulation-api-outage-recovery-2026-10-16.json). The latter records a same-route recovery after stopping and restoring only the validation API. The API is left running with its normal 900-second stream duration. The root review also records passing `npm run check`, measured desktop alignment and keyboard focus behavior in [coordinator review](evidence/simulation-coordinator-review-2026-10-16.json). The [Worker asset routing check](../deploy/worker) passed against the final build; no Worker source or deployment was changed.

The final captures include the [run index](screenshots/simulation-directory-1920x1080.png) and paired narrative and competition routes at 1920×1080, 1363×936, 1440×900, 1024×768, 768×1024, and 390×844:

- Narrative: [1920×1080](screenshots/simulation-narrative-1920x1080.png), [1363×936](screenshots/simulation-narrative-1363x936.png), [1440×900](screenshots/simulation-narrative-1440x900.png), [1024×768](screenshots/simulation-narrative-1024x768.png), [768×1024](screenshots/simulation-narrative-768x1024.png), [390×844](screenshots/simulation-narrative-390x844.png).
- Competition: [1920×1080](screenshots/simulation-competition-1920x1080.png), [1363×936](screenshots/simulation-competition-1363x936.png), [1440×900](screenshots/simulation-competition-1440x900.png), [1024×768](screenshots/simulation-competition-1024x768.png), [768×1024](screenshots/simulation-competition-768x1024.png), [390×844](screenshots/simulation-competition-390x844.png).
- Landing regression: [desktop](screenshots/simulation-landing-desktop-1920x1080.png), [mobile](screenshots/simulation-landing-mobile-390x844.png), [shared desktop](screenshots/simulation-landing-shared-1920x1080.png), and [shared mobile](screenshots/simulation-landing-shared-mobile-390x844.png). The [publication audit](evidence/simulation-landing-publication-2026-10-16.json) records the merged public release's seven path checks; the hosted API is unavailable by design.

## Reproduce

The API, Vite preview, and disposable PostgreSQL database use ports 8026, 5186, and 15436. The retained API services on 8000 and 8010 and retained database on 15432 were left untouched. Store the dedicated database URL in `/tmp/arena-sim-validation-20261016.dburl`; never commit that file.

On a fresh disposable database, run migrations and the real replay seed once:

```sh
DATABASE_URL="$(cat /tmp/arena-sim-validation-20261016.dburl)" PYTHONPATH=services/api uv run python -m app.cli migrate
DATABASE_URL="$(cat /tmp/arena-sim-validation-20261016.dburl)" PYTHONPATH=services/api uv run python -m app.cli seed-demo --rounds 20
```

Do not seed the existing validation database again. Start the API and Vite from the repository root in separate terminals:

```sh
DATABASE_URL="$(cat /tmp/arena-sim-validation-20261016.dburl)" PYTHONPATH=services/api uv run uvicorn app.main:app --host 127.0.0.1 --port 8026
```

```sh
npm run dev -- --config .review/vite.sim-validation.config.mjs --port 5186 --strictPort
```

The ignored Vite config proxies `/api/v1` to the isolated API. Run the read-only browser/API suite from the assigned worktree:

```sh
SIMULATION_API_BASE_URL=http://127.0.0.1:8026/api/v1/public \
SIMULATION_BASE_URL=http://127.0.0.1:5186 \
CHROME_DEVTOOLS_AXI_SESSION=arena-sim-validation-20261016 \
node scripts/simulation-browser-validation.mjs --fixtures
```

The runner writes `docs/evidence/simulation-browser-validation-2026-10-16.json`, captures the selected-run routes, and stops only its named browser session. Use `--functional-only` to skip captures or `--api-only` to run only API checks. The default runner does not create or mutate fixtures.

To create the optional empty, running, paused, and unavailable-rules fixtures in this disposable database, run the ignored helper once:

```sh
DATABASE_URL="$(cat /tmp/arena-sim-validation-20261016.dburl)" \
PYTHONPATH=services/api uv run python .review/seed-simulation-validation.py
```

The helper creates four service-backed records labeled `TEST FIXTURE`; it starts no worker and makes no provider requests. It is local-only and is not committed.

The original UI baseline capture and fixture helper are kept under ignored `.review/` files. The suite hashes downloaded Blob bytes inside the browser before comparing them with API metadata, so it does not transfer large byte arrays through the browser tool.
