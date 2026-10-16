# Landing mark validation — 2026-10-16

The landing header and footer now use the supplied Open Alpha Arena Lab mark, while the bottom visualization settles to the same near-black bracket and green alpha geometry. The existing five-scene landing sequence and its transitions remain in place.

The copied public assets were compared with the originals in `logos/oaal-logo/`; SHA-256 hashes match for `oaal-mark-light.svg` (`15f5ab98d2bc9f7cfc37a8e679ab97379ff597ee39978f9e4c16ce4381b53484`), `oaal-mark-dark.svg` (`7802e5b273dd13be547ed52979523028ea4499207888943a6b5cb954a76b25c2`), and `oaal-lockup-light.svg` (`6b8e0f87a24e226acc559ca1899f04e90569eabf76e18423f419059eb793b761`). The canvas settled mark was compared against the supplied light mark SVG at 411×411 pixels: opaque bounds matched exactly (`48,48`–`362,362`) and the alpha-mask agreement was 99.6478% (IoU 98.6699%). The small difference is raster antialiasing.

Browser checks used an isolated Vite preview and a named Chrome DevTools AXI session. At 390px viewport width, document scroll width stayed 390px and the header lockup measured 124×45.7px. Under forced `prefers-reduced-motion: reduce`, the media query matched and hero animation was disabled. The forced SVG-fallback state displayed the same supplied mark. Forward and reverse scene transitions were sampled independently; progress advanced in the requested direction toward scenes 4 and 3, respectively. No console errors were observed during the scene transition checks.

Screenshots:

- [Desktop landing, 1920px](screenshots/branding-landing-desktop-1920.png)
- [Mobile header, 390px](screenshots/branding-landing-mobile-header-390.png)
- [Mobile footer, 390px](screenshots/branding-landing-mobile-footer-390.png)
- [Reduced-motion landing](screenshots/branding-landing-reduced-motion.png)
- [SVG fallback](screenshots/branding-landing-svg-fallback.png)

These are local preview artifacts; no deployment or publication was performed.
