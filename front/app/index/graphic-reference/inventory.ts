import materialNames from '@quasar/extras/material-icons/icons.json'

export interface GraphicEntry { name: string; sources: string[] }
export interface GraphicInventory { glyphs: GraphicEntry[]; components: GraphicEntry[] }

/** Include literals inside bound expressions and presentation maps, not just icon attributes. */
export function graphicInventory(sources: Record<string, string>, knownGlyphs: Iterable<string>): GraphicInventory {
  const known = new Set(knownGlyphs)
  const glyphs = new Map<string, Set<string>>()
  const components = new Map<string, Set<string>>()
  const add = (map: Map<string, Set<string>>, name: string, source: string) => {
    if (!map.has(name)) map.set(name, new Set())
    map.get(name)!.add(source)
  }
  for (const [file, source] of Object.entries(sources)) {
    const path = file.replace(/^.*?(core|app|bridge)\//, '$1/')
    for (const match of source.matchAll(/['"`]([a-z0-9_]+)['"`]/g)) {
      if (known.has(match[1]!)) add(glyphs, match[1]!, path)
    }
    const template = file.endsWith('.vue') ? source.replace(/<(script|style)\b[\s\S]*?<\/\1>/g, '') : ''
    for (const match of template.matchAll(/<([A-Z][A-Za-z0-9]+|q-[a-z-]+)(?=[\s/>])/g)) {
      add(components, match[1]!, path)
    }
  }
  const entries = (map: Map<string, Set<string>>) => [...map].sort(([a], [b]) => a.localeCompare(b))
    .map(([name, files]) => ({ name, sources: [...files].sort() }))
  return { glyphs: entries(glyphs), components: entries(components) }
}

// This module is reachable only from the dev page, excluded from other builds.
const sources = import.meta.glob<string>([
  '../../../{core,app,bridge}/**/*.{vue,ts}',
  '!../../../**/*.test.ts', '!../../../**/emoji/**',
  '!../graphic-reference/**', '!../pages/graphic-reference.vue',
], { query: '?raw', import: 'default', eager: true })
const names = materialNames.map(name => name.slice(3).replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase())
export const inventory = graphicInventory(sources, names)
export const artwork = Object.keys(import.meta.glob([
  '/public/menu-icons/*.svg', '/public/editor-icons/gnome/**/*.png',
  '/public/editor-icons/gnome/*.svg', '/public/provider-logos/*.{svg,png}',
  '/core/util/icons/**/*.svg', '/public/logo/*.{svg,png}',
])).map(file => file.replace('/public', '')).sort()
