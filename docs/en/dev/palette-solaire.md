<p align="right"><a href="../../fr/dev/palette-solaire.md">Français</a> · <strong>English</strong></p>

# Solaire palette — application reference

Approved on September 10, 2026. This palette defines the colors to use throughout the Galaris
interface: navigation, icons, buttons, blocks, badges, states, dialogs and charts, across
`core`, `app` and `bridge` modules.

The palette contains exactly **11 colors and 33 shades**. The values below match the last
approved preview, with neutral gray added, and supersede earlier proposals.
[Decision 0081](../../../project/decisions/0081-solaire-color-reference.md) records their adoption.

Internal process diagrams use a drawing-specific exception: they follow the reference SVG
“01 2026-09-23 schéma processus révision” (slate lanes, blue-gray cards
`#F1F5F9` / `#94A3B8`, amber `#FEF3C7` / `#D97706` and deep green
`#DDF3EF` / `#0F766E`). These values are centralized in
`front/app/process/processDiagram.css`, shared with thumbnails and drag previews.
Controls, Start/End events and execution states retain Solaire colors. The light theme
reproduces the SVG backgrounds; the dark theme adapts these families with cards distinct
from lanes. This exception adds no accents to the rest of the application.
Rows alternate between the two lane backgrounds from the first row onward; the system
lane has no separate background.

| Diagram surface | Reference light background | Adapted dark background |
|---|---|---|
| Lane | `#FBFCFD` | `#151C26` |
| Alternating lane | `#F6F8FB` | `#1B2431` |
| Blue-gray card | `#F1F5F9` | `#283547` |
| Amber card | `#FEF3C7` | `#463914` |
| Deep green card | `#DDF3EF` | `#153D39` |

Gray and amber outlines retain `#94A3B8` and `#D97706`; the green outline
`#0F766E` becomes `#4BA99B` in dark mode. SVG strokes retain their fractional widths.

## Exact values

| Stable key | Color | Vivid accent | Light background | Dark background |
|---|---|---|---|---|
| `yellow` | Sun yellow | `#FFE610` | `#FFF4DE` | `#383517` |
| `orange` | Solar orange | `#FF9A00` | `#FFF7EB` | `#382A15` |
| `salmon` | Salmon | `#FA8072` | `#FFF5F4` | `#382725` |
| `red` | Solar red | `#F43636` | `#FEEFEF` | `#371C1C` |
| `fuchsia` | Fuchsia | `#D936B5` | `#FCEFF9` | `#331C2E` |
| `violet` | Orchid | `#AD3CE6` | `#F8EFFD` | `#2D1D35` |
| `iris` | Iris violet | `#854CF0` | `#F5F1FE` | `#271F36` |
| `blue` | Bright blue | `#087FF5` | `#EBF5FE` | `#162637` |
| `cyan` | Cyan | `#00B8D4` | `#EBF9FC` | `#152E32` |
| `green` | Leaf green | `#11A653` | `#ECF8F1` | `#172C20` |
| `gray` | Neutral gray | `#808080` | `#F5F5F5` | `#272727` |

Keys identify Solaire colors, not native Quasar colors. In particular, `violet` denotes Orchid
and `iris` denotes Iris violet.

## Usage rules

- Use vivid accents for colored markers and the matching backgrounds for tinted surfaces.
  A block keeps its color family when switching themes.
- Consume the exact values through a shared definition when integrating them into code.
  Do not scatter hex literals across components, recalculate variants per module, or substitute
  a similar-looking Quasar color.
- Keep general surfaces and text neutral. The approved preview uses `#FFFFFF` and `#101010`
  for light and dark general surfaces, with `#292C30` and `#EEEEF0` text respectively.
  These neutrals are not additional accents.
- Horizontal and vertical resizable separators use the same colour as native Quasar borders,
  adapted to the light or dark theme. Keep their native background instead of substituting
  a Solaire grey or accent; the visual reference shows both orientations inside a bordered
  card using that same colour.
- Choose readable neutral text for each background; a vivid accent does not by itself ensure
  small-text readability. Pair states with a label or icon.
- Keep color meanings consistent between screens. The palette does not require every component
  to use all eleven colors at once.
- Any palette change must update the shared reference and its translation. Earlier exploration
  files under `work/` are not authoritative.

**Removed colors:** Amber, Tangerine, Coral, Raspberry, Bright pink, Azure, Jade and Emerald.
Do not reintroduce them as additional accents.

## Origin of the approved backgrounds

Values were obtained by interpolating sRGB channels, rounding to the nearest integer, then
approved visually:

- light background: 8% accent and 92% white `#FFFFFF`;
- yellow light-background exception: 14% `#FFB010` and 86% white, yielding `#FFF4DE`;
- dark background: 14% accent and 86% `#181818`.

The yellow exception applies only to its light background. Its vivid accent remains `#FFE610`.
Consume the table's hex values as the reference, without additional interpolation.

## Adoption

### Permission actions

The Permissions page shares one presentation across toggles, badges and counters:
green for allow/enable (check), red for deny/disable (cross), orange for ask
(question mark) and pending approval (waiting), gray for inheritance (merged branches).
A double check distinguishes permanent approval; the block symbol distinguishes
permanent denial. Ordinary actions remain blue.

Scopes use cyan/eye for usage, blue/person for personal, iris/group for team and
violet/globe for all. No delegation uses red, inheritance gray. Choices stay in one row,
with an icon, translated tooltip and accessible label. The current choice has a filled
accent background and underline; other choices use their family's light or dark
background, following skill authorization controls.

### Single source and CSS variables

All 33 values are defined once in `front/core/util/solaire.ts`.
`solaireTheme.ts` automatically derives a global stylesheet:
`--solaire-blue-accent`, `--solaire-blue-light`, `--solaire-blue-dark`, and equivalent
variables for the other ten colors. There is no separate SCSS palette copy.

Styles use `var(--solaire-blue-accent)`. For dynamically selected colors, import
`solaireCss` from `@/core/util`: `solaireCss[color].accent`, `.light` and `.dark`
reference these variables. The literal `solaire` table is reserved for exports.
Editing a shade in the source updates consumers through Vite reload in development
and the next production build. Each color retains three explicit shades, matching
the approved values above.

Preferences, Laboratory, folders and code highlighting consume these
variables. Folders render inline SVG, so their display requires no image regeneration.
Standalone print and export documents embed the stylesheet derived from the same source.
After a palette change, inspect these consumers visually in both themes. Functional tests
do not freeze their colors or visual grouping.

The “Models in use” page applies light or dark Solaire backgrounds to usage group
headings. Its tables and controls retain the interface theme colors.

This reference sets the target for all visual changes. Documenting its adoption does not mean
every historical runtime style has already been replaced. Code harmonization must use these
values and verify rendering in both themes.

With `APP_ENV=dev`, **Developers → Visual reference** (`/graphic-reference`) brings
together real components, folders at their display sizes, glyphs and editors.
The “Toggle button groups” section includes exclusive choices, independent selections
and the actual skill authorization buttons in active, blocked, unselected and disabled states.
Consult this page before a visual change to compare elements, then check the affected consumer in the
application. Its interactions stay local; it does not load personal user icons. Domain
components are composed in `front/graphicReferenceContributions.ts`, following the existing
frontend composition root pattern.
