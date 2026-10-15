# Landing reference validation

This revision replaces the illustrative geometry and authored spring animation at `1596ce7` with a reconstruction based on the current public Nof1 renderer, inspected on 15 October 2026. Open Alpha Arena keeps its own name, copy and OA mark. Earlier validation reports and screenshots remain in Git history; they describe superseded approximations, including 658 interpolated contours, 282 chart cubes and equal-height logo-strip flights.

## Reference evidence

**EXACT — public implementation and DOM/CSS.** The current page serves renderer chunk `0gvneg1-scdrw.js`, SHA-256 `fe3a8eec9144bc31bdd60c62ddd5345a9470e2eecbfc856b0ebab9492be9fd02`, and shared geometry chunk `1ktnajvnydr6e.js`, SHA-256 `fe9ae6fdddf18a8ab3fe8014bd07eb9b9dad183880d2487d50ebbc3f4ef07b88`. The page, assets and extraction scripts are retained in the local ignored `.review/reference-20261015/` directory. No production code loads the reference JavaScript.

The public generator establishes 220 source panels, 721 samples per profile, selected panel 122, a 20 × 11 grid, six chart boundaries and a deterministic orthographic lattice. The lattice contains **512 cubes**, with family counts 96/60/160/100/60/36; an initial working-note total of 824 was an arithmetic error. An independent VM execution of the public pure generators checked reconstructed mountain, chart, lattice and departure-packing data. Review caught and corrected noise hash argument order, foreground depth, random-number consumption and chart-boundary interpolation.

The reference runs its main **WebGL2 path through SwiftShader** in our ordinary headless Chromium session. Its auxiliary chart/lattice canvases are 2D even in that path. The software-WebGL deprecation warning does not mean the reference selected its Canvas painter. Reduced motion was false. The first active WebGL2 context was not lost; no shader/context errors or painter-fallback warning appeared.

**OBSERVED FALLBACK.** A separate reference session launched with `--disable-webgl` emitted the exact Canvas-painter fallback warning. Its settled mountain was captured separately from the WebGL2 mountain, so shader edge treatment is not confused with geometry. The user's earlier fallback observations remain evidence for crossfades, retained chart outlines/scaffolding, and the persistent models legend, rather than proof of spatial flight paths.

**NATIVE TO VERIFY.** Software WebGL is not physical GPU validation. Source code establishes trajectories and clocks where listed in the [motion manifest](landing-motion-manifest.md). The replica uses the reconstructed native WebGL shader, followed by the reference's cached-Canvas compositing approach. Independent shader comparisons and timed illustration samples support this reconstruction; they do not certify every complete page frame. Physical-device, Safari and complete assistive-technology sessions remain outside this pass.

## Layout and assets

The page uses normal document scrolling, a static header, 1440 px container, 24/40 px gutters, 12-column desktop grids, 64 px column gaps and the 1024 px stacked breakpoint. Hero geometry uses the overlapping source grid and viewport-height cap. Section sizes follow content and art aspect ratios instead of fixed desktop heights. On-chart annotations appear at 1280 px and use DOM text, 160 px balanced boxes, non-scaling leaders and a 3 px background text stroke. Below that breakpoint, the chart reserves its 6% gap overhang and has a six-item explanation list 32 px beneath it.

Signifier Roman/Italic faces are available in the local comparison build, with provenance in `apps/web/public/fonts/SOURCES.md`. Newsreader's OFL does not cover those faces. The project copy changes line wrapping; this page does not assert Nof1's research, team, backing or results. The OA mark and simulation navigation intentionally differ from the reference.

At 1363 × 936, our Chromium document client width is 1363 px. The supplied earlier measurements used 1348 px after a 15 px scrollbar. Comparisons here use equal actual browser client widths; earlier absolute coordinates are not silently treated as identical measurements.

## Repeat the comparison

```sh
npm install
npm run build
npm run dev -- --port 4173
```

Open `http://localhost:4173/`. The build and browser captures require no API or provider credentials. To capture all five scenes at 1363 × 936, 1440 × 900, 1024 × 768, 768 × 1024 and 390 × 844:

```sh
node scripts/capture-landing.mjs http://localhost:4173 /tmp/arena-landing-captures
node scripts/capture-landing.mjs https://www.nof1.ai/ /tmp/nof1-reference-captures
```

The script records actual scroll, client width, heading/font state and art/section bounds, checks missing/zero-sized art and document overflow, and saves 25 screenshots per page. Its geometry checks are not a pixel-fidelity assertion. Set `CHROME_DEVTOOLS_AXI_BIN` if the browser command is outside `PATH`.

To sample all four native illustration transitions while scrolling pauses after each trigger:

```sh
node scripts/capture-landing-motion.mjs http://localhost:4173 /tmp/arena-motion-captures
```

This tool copies actual Canvas layers inside animation callbacks and records elapsed times at nominal 0/100/200/300/450/600/900/1200/1800/2400 ms checkpoints. It saves 40 PNGs plus a manifest. The images exclude DOM text and chart scaffolding; the static capture tool covers those. Sampling adds overhead, and this is not a frame-rate benchmark or a calibrated 60 fps recording.

To check resize behaviour during a selected-profile flight, during the chart split, after a height-only (mobile URL bar) resize at 390x844, and after a 844x390 orientation change:

```sh
node scripts/check-landing-resize.mjs http://localhost:4173
```

It exits non-zero if a resize marks the chart landed early, restarts the split, drops a settled stage on a height-only resize, or leaves an incoherent stage after a width change.

## Current verification

`npm run check` passed TypeScript checking and the production build. Reference and replica capture matrices cover all five scenes at the five requested viewports, with fonts ready and no horizontal document overflow.

The public generators and reconstructed data compare to numerical precision: maximum mountain-coordinate error 2.84e-12, chart error 1.25e-12, grid and lattice coordinates exact. Independent WebGL comparisons over about 3.66 million RGBA bytes per tested composition found at most one byte value of difference; context restoration replayed an identical frame. The static hero-art crop's mean RGB difference from the reference was about 0.57/255 per channel. This is evidence for the tested art crop, not an assertion about full-page pixel parity. All five art anchor bounds matched the live reference at 1363 × 936 and 1440 × 900 to the capture manifest's 0.1 px precision. Art dimensions matched at all five viewports; smaller-layout document positions depend on the retained project copy. The [anchor comparison](evidence/landing-anchor-comparison-2026-10-15.json) records both sets of bounds and their deltas.

Twenty native browser checks and twenty separate forced-no-WebGL checks passed; their states and the five final shell checks are retained in the [browser results](evidence/landing-browser-checks-2026-10-15.json). These cover stage ownership, chart separation and retained outlines, the persistent legend, forward/reverse hysteresis, End/Home, restored scroll, bottom resize and mobile overflow. Additional interruption checks caught four defects and then verified their fixes: repeated reversal retains phase, incoming endpoints stay hidden behind transfers, interrupted chart departure retains its landed split state, and early logo departure retains the moving cube mass. The independent Sol 6.1 review reported no remaining verified medium-or-higher rendering/lifecycle finding.

Actual context loss switched to Canvas fallback; restoration rebuilt native rendering without a GL error. Forced reduced motion exposed settled art at all five anchors. Complete Canvas failure exposed all five SVG scenes, the split chart and its explanatory list. The final responsive shell checks cover 1363, 1024, 768 and 390 px widths.

Representative captures are [hero](screenshots/landing-fidelity-hero.webp), [chart](screenshots/landing-fidelity-chart.webp), [lattice](screenshots/landing-fidelity-lattice.webp), [OA mark](screenshots/landing-fidelity-mark.webp), [mobile chart](screenshots/landing-fidelity-mobile-chart.webp), and [mid-transfer illustration](screenshots/landing-fidelity-transfer.webp). The [capture manifest](evidence/landing-captures-2026-10-15.json) records the full static matrix. The [timed sample manifest](evidence/landing-motion-samples-2026-10-15.json) records the illustration samples' actual times and stage state.

Remaining parity limits are physical-device/Safari behavior and calibrated full-page temporal comparison. The OA bitmap, project text and simulation navigation intentionally retain this project's identity. No deployment or source publication was performed.
