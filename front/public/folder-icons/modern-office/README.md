# Modern Office folder artwork

Source: **Modern-Office-Day-Icons 1.4.18**, `places/32/athena.svg`, by DrMcC0y.
Project: https://github.com/DrMcC0y/Modern-Office-Day-Icons

The unmodified reference is preserved in `source/athena.svg`. Upstream credits are
in `AUTHORS`; the GNU GPL version 3 license is in `COPYING`.

Galaris adapts the artwork in `front/core/util/folderArtwork.ts`. The detailed
64 px drawing keeps the original geometry, gold colors and gradients with a fine
contour. A separate optical drawing at 16–32 px uses snapped panels, one 1 px
contour and no filters. Expanded folders open the front panel; eleven variants
use the central Solaire accent/light/dark values.
Each live icon has unique gradient/filter identifiers. `FolderIcon.vue` chooses
the drawing for its displayed size and renders it inline so palette changes
remain live in both themes. Small pixel sizes get their own aligned grid.

`front/scripts/build-folder-icons.mjs` exports the same artwork to
`/folder-icons/solaire/`, including `default/` for the gold folder.
`folder.svg` and `folder-open.svg` are the 24 px versions; suffixes `-16`, `-32`
and `-64` select the other native sizes. The graph uses the appropriate export
for its legend and node sizes.
Run it with Node inside the frontend container after changing the shared artwork.
The generated derivatives are licensed under GPL-3.0.
