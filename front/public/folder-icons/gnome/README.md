# Galaris folders in the Solaire palette

The initial design was derived from Jakub Steiner's `folder.svg` and `folder-open.svg`
in **gnome-icon-theme 2.20.0**, licensed under GPL version 2. Original metadata,
unmodified source artwork (`source/`), license (`COPYING`) and author credits
(`AUTHORS`) are included.

Source: https://download.gnome.org/sources/gnome-icon-theme/2.20/gnome-icon-theme-2.20.0.tar.bz2

The current artwork is redrawn on a native 24 px grid, inspired by the broad proportions
and rounded flap of [Windows 11 folders](https://commons.wikimedia.org/wiki/File:Windows_11_FOLDER.svg).
It uses solid Solaire panels, a narrow light inner lip and a subtle lower edge, without
outline strokes, gradients, blur or cast shadows. The SVG geometry is defined in
`front/core/util/folderArtwork.ts`, not copied from the Windows asset. The existing asset URLs and GPL-2.0 license
are retained.
The eleven variants are generated from the central `front/core/util/solaire.ts` palette by
`front/scripts/build-folder-icons.mjs`; run this script with Node in the frontend container
when standalone SVG files are needed. The application renders the same geometry inline
through `FolderIcon.vue`, using global `--solaire-*` CSS variables, so palette changes
apply immediately without regenerating image files.
Runtime roles use blue for agent-specific custom folders, red for custom folders containing
shared documents, and green for goal folders. Role and sharing come from document metadata
and access grants, not folder names. The same colors apply in the library and folder selector.
