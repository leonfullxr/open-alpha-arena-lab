# Frontend design system

The simulation workspace uses the semantic tokens in `apps/web/src/tokens.css` and the route-specific layout in `apps/web/src/simulation.css`. The production landing keeps its existing art direction and stylesheet. This separation lets the simulation share the production palette and mark without changing the landing composition.

## Palette

| Role | Light | Dark |
|---|---|---|
| Canvas | `#f9f9f8` | `#151411` |
| Surface | `#ffffff` | `#201e19` |
| Secondary surface | `#f1f0ef` | `#292721` |
| Border | `#dad9d6` | `#3d3b34` |
| Primary text | `#21201c` | `#f7f6f2` |
| Secondary text | `#63635e` | `#b0aea6` |
| Brand accent | `#00a15e` | `#38bd7a` |
| Positive | `#46a758` | `#68c17a` |
| Negative | `#e5484d` | `#f07174` |
| Warning | `#8d6500` | `#ffc53d` |

Status and financial meaning use text or signs alongside color. The shared tokens also define soft surfaces, focus, selection, and reduced-motion behavior. Coin marks use their asset colors as data identifiers, not as page accents.

## Type and numbers

- Simulation typeface: self-hosted Geist variable WOFF2, with system sans-serif fallbacks.
- Workspace base: 14px with a 1.55 line-height. The global landing base remains 15px.
- Page titles: 23–30px; section titles: 15–18px; table content: 12px; supporting labels: at least 11px.
- Numeric columns use tabular numerals and align to the right where comparison matters.
- Currency, percentage, decimal, and UTC timestamp formatting is centralized in `simulation/ui.tsx`.
- IDs and raw evidence remain available in contextual detail; they do not dominate summary rows.

## Layout and controls

- Desktop shell: 232px persistent sidebar, 58px context header, ticker strip, and a centered workspace capped at 1440px.
- Main content uses 24–32px gutters on desktop and 12–16px on narrow screens.
- Controls are generally 34–36px high. Table regions scroll internally when their full column set does not fit.
- Surfaces use fine borders and 8–10px radii. Shadows are reserved for transient chart tooltips.
- The simulation sidebar contains Simulation, Leaderboard, and Models. The protected admin app remains a separate entry and is not linked from this navigation.
- The header distinguishes competition state and market data freshness. The selected competition and URL-backed filters remain available while navigating between detail views.

## Charts, icons, and interaction

- Recharts is used for equity history. Series colors distinguish agents; semantic colors are reserved for positive and negative outcomes.
- Lucide React provides navigation, action, and tab icons. `AssetIcon` provides the supported coin marks; `ActionIcon` maps recorded actions to directional or neutral marks. Both preserve names with accessible labels and hover titles.
- Use links for navigation and buttons for actions. Add a subtle arrow icon to text links that open another page or record.
- Preserve keyboard focus, labelled scroll regions, semantic table headings, visible status text, and reduced-motion preferences.
- Loading, empty, and error states must remain scoped to the affected data. The frontend displays authoritative API values and does not calculate trading P&L.

## Ownership

`tokens.css` owns shared palette, typography defaults, focus, and accessibility preferences. `simulation.css` owns simulation layout and components; `styles.css` owns the production landing; `admin/admin.css` owns the protected admin app. Keep future visual changes in the route that owns the affected surface, and update this document when semantic tokens or shared conventions change.
