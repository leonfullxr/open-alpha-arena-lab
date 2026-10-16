# Landing font sources

The current landing stylesheet loads Signifier Roman and Italic variable WOFF2 faces. The files were publicly served by the reference homepage and retrieved 15 October 2026:

- https://www.nof1.ai/_next/static/media/signifier-vf-roman.3aqrr1no44ii2.woff2
- https://www.nof1.ai/_next/static/media/signifier-vf-italic.09hp43-yre30y.woff2

Signifier is by Klim Type Foundry. These files are included in the deployed landing build. This source note does not assert a redistribution licence. The `OFL.txt` file applies only to the separately bundled Newsreader font, not to Signifier.

Newsreader remains bundled under its open-font licence but is not used by the current landing stylesheet. See `OFL.txt` for its licence.

# Simulation font sources

The simulation terminal uses IBM Plex Mono (IBM Corp., SIL Open Font License 1.1). The four WOFF2 files are unmodified full-glyph conversions, made with fontTools, of the Debian `texlive-fonts-extra` package OpenType files (`IBMPlexMono-Regular.otf`, `-Medium.otf`, `-Bold.otf`, `-Italic.otf`) on 15 October 2026. `IBM-Plex-OFL.txt` is the licence copied from that package.
