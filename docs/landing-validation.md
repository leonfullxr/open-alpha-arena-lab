# Landing validation

The original integration checkpoint was checked on 2026-10-15 in local Chromium against the Vite development build. The landing was accepted before simulation frontend implementation began. The reference fidelity revision below follows the user's subsequent visual review.

The five scenes use original deterministic geometry: 220 terrain slices, a 20 by 11 grid, six annotated chart spans, six lattice families, and a 36-strip tiled mark. The chart and grid captions identify conceptual artwork. The layout follows the supplied PDF's measurements and palette; original geometry and transfer trajectories are adaptations, rather than recovered reference animation data.

## Browser evidence

| Viewport | Capture |
| --- | --- |
| 1363 × 936 | [Hero](screenshots/landing-1363x936.webp) |
| 1440 × 900 | [Hero](screenshots/landing-1440x900.webp) |
| 1024 × 768 | [Hero](screenshots/landing-1024x768.webp) |
| 768 × 1024 | [Hero](screenshots/landing-768x1024.webp) |
| 390 × 844 | [Hero](screenshots/landing-390x844.webp) |

Settled illustrations: [grid](screenshots/landing-grid.webp), [chart](screenshots/landing-chart.webp), [lattice](screenshots/landing-lattice.webp), [mark](screenshots/landing-mark.webp).

The primary inspected desktop, tablet and mobile layouts, five accessible scene anchors, one page H1, contained copy and horizontal overflow. Slow and fast scrolling, reverse transfers, pauses, Home navigation and desktop-to-mobile resize were exercised. Review found and corrected overlapping tablet hero artwork, desktop grid auto-placement, a blank mountain after resize, and missing settled artwork in reduced-motion mode.

A separate Chromium process with reduced motion forced on retained all five static illustrations and readable content. A temporary test document made canvas contexts unavailable; all five SVG fallbacks and headings remained present. The temporary document was removed after the check.

During a desktop forward/reverse scroll sample, animation instrumentation recorded 307 callbacks, a maximum of one pending callback, 0.9 ms p95 callback time and 2.8 ms maximum callback time. There were no callbacks during a 400 ms settled interval. These are headless Chromium callback timings, not a measured frame-rate guarantee for physical devices.

After simulation integration, a production-preview browser trace loaded five JavaScript/CSS resources totaling 82,281 gzip bytes (about 80.4 KiB), below the 250 KiB limit. Fonts and artwork are excluded. The trace contained no API calls, chart modules or admin modules. Navigation to the simulation removed all landing canvases, reset scroll to zero and left no canvas-failure class. The landing remained readable with the API unavailable. The self-hosted Newsreader font is 121,024 bytes.

## Limits

Safari, physical mobile hardware and a complete assistive-technology session have not been tested. The recorded captures establish the landing checkpoint; later shared-shell changes require a final regression check. Production hosting remains unreviewed and undeployed.

Final integration budget check, 2026-10-15: all seventeen emitted JavaScript/CSS files across the landing, simulation and admin entries total 143,777 bytes at gzip level 6 (165,997 bytes at level 1). Even that complete-build sum is below the landing's 256,000-byte allowance; fonts and artwork are excluded. The accepted landing-only browser trace and animation observations above remain the direct loading/motion measurements. Final Home and Methodology navigation and the landing's zero API requests were checked again during simulation regression.

## Landing follow-up, 2026-10-15

The follow-up fixes three animation defects found during a read-only GPT-6.1 Sol review. The mountain-to-grid transfer now scales its destination to match the settled grid. Resize measures the current scroll position before selecting a scene. Scene thresholds stay within the document's reachable scroll range, so the final mark appears in tall windows.

Luna validated the production preview at 1440 by 900, 768 by 1024 and 390 by 844. All five scenes rendered, copy fit, and document width matched each viewport. Forward and reverse scrolling, Home and Methodology navigation passed. At 1440 by 1200, the final mark rendered after fresh navigation to the bottom and after increasing the height from 900 while already at the bottom. The primary independently built the frontend and ran the three browser regressions. Sol's correction review found no medium-or-higher defect.

The local browser regression script compares the actual transfer paths with the settled canvas paths and checks the final mark's pixels. All three checks failed when their corresponding fixes were removed. Mutation sources were restored byte for byte. The scripts, logs and follow-up screenshots remain local evidence. Safari, physical-device and assistive-technology checks remain pending.

## Reference fidelity revision

The user's four landing screenshots establish the visual targets for this revision. Their 1920 by 1080 captures include 149 pixels of browser chrome, so comparison captures use a 1920 by 931 page viewport. The content spans x280 to x1640, the hero heading starts at y346 and the hero divider sits at y718.

The terrain has a shared base and 220 source profiles with decreasing elevation toward the foreground. The later density revision interpolates between those profiles to render 658 contours, while retaining the original grid and selected profile. The chart samples the selected profile, fills six pastel spans and opens narrow gaps without translating their coordinates. Its leaders attach to that same plotted contour. The lattice uses five colored clusters and a gray center, with shaded cube faces. The original OA monogram uses outlines from the bundled Newsreader font, a fine mosaic pattern and a tiled frame. Header and footer use a dark version of the same geometry; the favicon retains the mosaic colors.

| Scene | Revision capture |
| --- | --- |
| Mountain and hero | [Desktop hero](screenshots/landing-reference-hero.png) |
| Filled chart and callouts | [Desktop chart](screenshots/landing-reference-chart.png) |
| Formed chart cubes in transit | [Cube transfer](screenshots/landing-reference-cube-transfer.png) |
| Cube field | [Desktop lattice](screenshots/landing-reference-lattice.png) |
| Original tiled OA mark | [Desktop mark](screenshots/landing-reference-team.png) |
| Stacked mobile hero | [Mobile hero](screenshots/landing-reference-mobile.png) |

To repeat the captures against a running frontend, use `chrome-devtools-axi` and Node:

```sh
node scripts/capture-landing.mjs http://localhost:5173 /tmp/arena-landing-captures
```

Set `CHROME_DEVTOOLS_AXI_BIN` if the browser command is outside `PATH`. The script writes five desktop and five mobile screenshots plus a manifest of actual viewport, scroll and element bounds. It checks dimensions, missing content and overflow. Inspect the resulting artwork against the references; passing those geometry checks does not establish visual fidelity. The script's baseline hero capture matched the independent manual capture byte for byte.

The primary independently built the final source and captured all ten scenes. The five saved revision screenshots match those independent captures byte for byte. The three animation regressions passed again: the mountain-to-grid endpoint matched the settled grid within one CSS pixel, and the final mark rendered both after a bottom-of-page resize from 1440 by 900 to 1440 by 1200 and after fresh navigation in the taller viewport. The updated preview at port 4173 loaded the revised assets, made no API requests and had no horizontal overflow at 1920 by 931.

Luna checked 1920 by 931, 1440 by 900, 1024 by 768, 768 by 1024 and 390 by 844 with no document overflow. Forward and reverse scrolling, Home and Methodology navigation, chart labels, the lattice legend and the final mark after resize passed. A reduced-motion session retained nonzero artwork dimensions. Manually activating the app's canvas-unavailable class exposed all five SVG fallbacks with geometry and matching layout boxes; the fallback capture visibly rendered the mountain, profile grid and filled chart. This last check exercised the fallback presentation, rather than simulating a failed canvas context.

GPT-6.1 Sol reviewed the source, capture tool and four desktop comparisons and found no medium-or-higher defect. The user's visual acceptance remains pending. This revision does not establish Safari, physical-device or complete assistive-technology coverage; simulation layout work and the accessibility pass remain separate follow-ups.

## Density and motion follow-up

The opening mountain now renders 658 contours in both Canvas and SVG. Its silhouette, placement and 220 source profiles stay fixed. The chart forms the arena's 282 shaded cubes inside its six filled regions before departure. Those same cube identities follow reversible curved routes into the existing lattice; chart context fades during departure and lattice connections appear near arrival. A scalar critically damped phase carries position and velocity across scroll retargeting. The mountain-to-grid and lattice-to-mark handoffs also crossfade their source artwork.

The primary captured ten controlled-clock chart-to-arena frames from actual Canvas drawing calls. All 282 cubes were present in the formed chart, each sampled transfer frame and the settled arena. Departure centers matched within numerical precision; the near-arrival centers matched the settled lattice within 0.05 CSS pixels. A reverse scroll crossed the actual hysteresis boundary and restored the chart; a rapid forward/reverse retarget also restored all 282 visible chart cubes. These checks establish geometry and visibility, not physical-device frame rate. The earlier callback timing measurements describe the original integration, rather than this revised animation.

The checks caught a double-applied chart transform and an opaque paint flash at the mountain's departure. Cube coordinates are now applied once. Transferring profiles share the settled grid's paint function and fade in, while the retained mountain clips to its original artwork box. The screenshots above were refreshed after the density and cube changes; local controlled-frame captures also cover the first and final handoffs.

The primary's final build and all three earlier animation regressions passed again. The grid endpoint differed from its settled geometry by less than one CSS pixel, and the final mark remained visible after tall-window navigation and bottom-of-page resize. Sol's read-only follow-up found no remaining medium-or-higher defect in cube containment, identity routes, spring retargeting, handoffs or reduced-motion handling.

Luna's independent live checks at 1440 by 900 and 390 by 844 found no remaining defect. Forward and reverse transitions, quick reversal below hysteresis, contained chart cubes and captions, arena and mark endpoints, and document overflow checks passed. The revised first transfer retained visible artwork until the grid settled. A reduced-motion mobile session retained chart and lattice ink and the contained six-item legend. Both validation browser sessions were stopped after the checks.
