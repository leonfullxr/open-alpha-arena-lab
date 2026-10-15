# Landing validation

Checked 2026-10-15 in local Chromium against the Vite development build. The landing was accepted before simulation frontend implementation began.

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
