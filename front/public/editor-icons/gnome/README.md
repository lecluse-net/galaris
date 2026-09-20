# GNOME editor icons

Unmodified 24 × 24 PNG icons from **gnome-icon-theme 2.20.0**, the collection shown at
https://commons.wikimedia.org/wiki/GNOME_Desktop_icons.

Upstream source archive:
https://download.gnome.org/sources/gnome-icon-theme/2.20/gnome-icon-theme-2.20.0.tar.bz2

Licensed under the GNU General Public License, version 2. The original license and author
list are included as `COPYING` and `AUTHORS`.

Icons originate from the archive's `24x24/actions/` directory, except:

- `accessories-character-map.png`: `24x24/apps/`;
- `text-x-script.png`, `x-office-spreadsheet.png`: `24x24/mimetypes/`.
- `stock_zoom-page-width.png`: `24x24/stock/navigation/`.

The CKEditor integration displays these PNG files at their native 24 × 24 CSS pixel size,
inside the editor's required SVG icon container. These are upstream's small bitmap variants,
not browser reductions of the scalable artwork. Commands without a corresponding GNOME
icon retain their native CKEditor icon. The previous scalable originals remain alongside
the PNGs as source artwork, with their metadata preserved; the editor no longer loads them.
