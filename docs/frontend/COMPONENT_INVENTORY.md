# Simulation frontend components

## Workspace shell

`SimulationShell` in `apps/web/src/simulation/shell.tsx` provides the production logo, primary navigation, competition selector, status context, market ticker, theme switch, keyboard skip link, and footer. It is shared across the public simulation routes.

## Routes and feature components

| Route | Component | Main job |
|---|---|---|
| `/simulation` | `DirectoryPage` | Select a public competition. |
| `/simulation/:competitionId` | `CompetitionPage` | Understand a run, inspect equity, compare leaders, and review activity. |
| `/simulation/:competitionId/leaderboard` | `LeaderboardPage` | Sort, filter, and compare account metrics. |
| `/simulation/:competitionId/models` | `ModelsDirectoryPage` | Browse every model account in the selected run. |
| `/simulation/:competitionId/models/:agentId` | `ModelPage` | Inspect one model's overview, fills, positions, and decisions. |

Shared feature components:

- `EquityChart` — responsive multi-agent equity plot, series toggles, time ranges, and tooltip.
- `ActivityPanel` — fills, model decisions, positions, research notes, and evidence details.
- `AgentLink` — contextual navigation from a model name to its account analysis.
- `AssetIcon` and `ActionIcon` — accessible coin marks and compact trading-action indicators.
- `PageHeading`, `QueryState`, `StatusBadge`, and `DataStatus` — shared page hierarchy and API states.

## Implementation boundaries

- TanStack Query owns remote data fetching and caching. URL search parameters hold shareable leaderboard and activity state.
- API adapters in `simulation/api.ts` define public request and response boundaries.
- Recharts renders equity values returned by the API; financial arithmetic stays outside the UI.
- Native links, buttons, inputs, selects, tables, tabs, and disclosures remain the interaction primitives.
- `tokens.css` owns shared semantic tokens. `simulation.css` owns simulation geometry and component styling.
- Admin remains a separate protected application entry, outside the public simulation navigation.
