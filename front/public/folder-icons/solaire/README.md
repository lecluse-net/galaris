# Galaris folders in the Solaire palette

The active icons are adapted from **Modern-Office-Day-Icons 1.4.18**,
`places/32/athena.svg`, by DrMcC0y, under **GPL-3.0**. See
[`../modern-office/`](../modern-office/) for the original artwork, credits, license
and adaptation notes.

`front/scripts/build-folder-icons.mjs` generates the default gold folder and eleven
Solaire variants, closed and expanded, from `front/core/util/folderArtwork.ts` and
the central palette. The default URLs contain the 24 px optical drawing; `-16`
and `-32` suffixes provide other small grids, and `-64` selects the detailed
drawing with fine contours. `FolderIcon.vue` renders the appropriate artwork inline
using global `--solaire-*` variables.

Runtime roles use blue for agent-specific custom folders, red for custom folders
containing shared documents, and green for goal folders. Role and sharing come from
document metadata and access grants, not folder names. The same colors apply in
the library and folder selector.
