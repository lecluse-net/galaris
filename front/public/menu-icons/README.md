# Galaris menu icons

Original SVG artwork shared by the sidebar, page headings, and preferences and
laboratory cards. Harness entries retain their original provider logos.

Each icon uses a 32 × 32 viewBox and rounded strokes.
Artwork supports 24–64 px displays on light and dark backgrounds. Files are
self-contained vectors without fonts, embedded bitmaps or external resources.

All artwork is monochrome: pure black in the light theme and pure white in
the dark theme. SVG luminance masks preserve transparent details and separate
overlapping shapes. There are no coloured fills or gradients.

The shared `front/core/navigation/icons.css` stylesheet follows Quasar's
`body--dark` class, including manual theme changes, and inverts only menu SVG
images. The same artwork is used in navigation, page headings and section cards.

The shared mapping lives in `front/core/navigation/icons.ts`. Related
entries intentionally share a pictogram (for example, conversations and messaging
preferences). Unmapped module icons retain their original appearance.

Open `preview.svg` for the complete contact sheet with both background colours.
