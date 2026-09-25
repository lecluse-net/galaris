<p align="right"><a href="../../fr/architecture/frontend-navigation.md">Français</a> · <strong>English</strong></p>

# Frontend navigation architecture

Navigation connects user intent to a screen. The [menu and workflow guide](../user/navigation.md)
describes visible steps; the [generated map](generated/navigation.md) and its
[JSON contract](generated/navigation.json) inventory shipped entries without assuming session permissions.

## Shell and menu composition

`front/modules.ts` activates modules. Each `navigation.ts` contributes a tree indexed by
stable keys. `core/navigation/tree.ts` recursively merges these trees in activation order
without mutating the original contributions. Modules can extend `admin.params.children`
without replacing other preferences.

`app/index/navigationSections.ts` orders the sidebar's five roots. `MainLayout.vue` hosts
the page container, mobile toolbar and account menu; `Sidebar.vue` displays sections with
at least one visible entry. Children are sorted by `order`, defaulting to 99. Labels and
descriptions resolve through i18n catalogs; internal names differ from displayed labels.

`core/navigation/composables/useNavigation.ts` filters each node: at least one required
privilege must be present, then its `visible` condition must pass. Hiding a parent hides
its descendants. These filters do not replace page, action or API authorization. A missing
menu does not prove a module is absent.

## Routes, submenus and tabs

`front/vite.config.ts` configures routes derived from `pages/` files. Menu `to` fields
provide navigation destinations. The general project map's `route_hint` column remains
indicative: do not use it to invent user-facing links.

Preferences and Laboratory construct submenus from their `presentation.ts` files;
Laboratory adds privileges from `access.ts`. Harnesses can add entries from the server
catalog. Those names and identifiers depend on the installation and are not frozen in documentation.

Tabs belong to Vue pages and components. A tab name does not automatically define a URL
parameter. The user guide documents actual `?tab=` links for Tools, Skills, LLM and Activity,
and interactions without direct links such as Memory tabs. The account menu is a separate
component with profile, tokens, personal preferences and role switching.

## Generating and maintaining agent documentation

`front/scripts/navigation-context.mjs` reads active modules, loads their declarations and
reuses the runtime merge. It loads FR/EN catalogs and presentation data to produce
`docs/{fr,en}/architecture/generated/navigation.{md,json}`. Both JSON files include both
languages. Each entry exposes:

- its stable identifier, translated breadcrumbs, route and description;
- privilege groups, using OR within a group and AND across ancestors;
- additional conditions, including inherited ones;
- contributing source files.

The generator does not start Vue or query an installation. It loads only admitted data
modules; availability predicate imports are replaced by functions that reject execution.
A new unreviewed import or missing translation fails generation rather than producing an
incomplete map. This loader treats repository code as trusted; it is not a sandbox.

`make project-context` regenerates both general and menu maps in containers.
`make project-context-check` checks both; `make architecture-check` includes that check.
Generator tests verify composition, translations, inherited conditions, exclusion of
inactive modules and propagation of route changes.

When navigation changes, regenerate the map and update affected FR/EN workflows. The
generated map covers declared menus, not every button, modal tab or installation-specific
record: those workflows remain in the user guide, verified against actual components.

The documentation corpus ships these files with the product version. Galaris Admin exposes
them to search and generic reading; `documentation_catalog` advertises the guide and map
as entrypoints. The `galaris-knowledge` skill consults them to provide
**section → screen → tab → action** guidance. No session snapshots, user content or
secrets enter this map.
