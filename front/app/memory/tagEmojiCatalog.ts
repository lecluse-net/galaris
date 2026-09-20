export interface TagEmojiIcon { code: string; value: string; family: 'emoji' | 'mdi' | 'awesome'; emoji: string; group: number; tone: number }
export interface TagEmojiMessages { documentTagEmoji: Record<string, { name: string; keywords: string }> }
export interface TagEmojiCatalog {
  icons: TagEmojiIcon[]
  messages: Record<string, TagEmojiMessages>
}

export function createFontCatalog(family: 'mdi' | 'awesome', glyphs: [string, string][], terms: Record<string, string>): TagEmojiCatalog {
  const icons: TagEmojiIcon[] = []
  const messages: Record<string, TagEmojiMessages> = Object.fromEntries(['en', 'fr', 'zh'].map(locale => [locale, { documentTagEmoji: {} }]))
  for (const [style, slug] of glyphs) {
    const code = `${style}-${slug}`
    const label = slug.replaceAll('-', ' ')
    const name = label.charAt(0).toUpperCase() + label.slice(1) + (style === 'far' ? ' (outline)' : style === 'fab' ? ' (brand)' : '')
    icons.push({ code, value: `font:${style}:${slug}`, family, emoji: '', group: -1, tone: 0 })
    for (const locale of ['en', 'fr', 'zh']) {
      messages[locale]!.documentTagEmoji[code] = { name, keywords: `${label} ${locale === 'fr' ? slug.split('-').map(word => terms[word] ?? '').join(' ') : ''}` }
    }
  }
  return { icons, messages }
}

type Family = 'emoji' | 'mdi' | 'awesome'
const catalogPromises = new Map<string, Promise<TagEmojiCatalog>>()
const installed = new Set<string>()

async function unicodeCatalog(language: string): Promise<TagEmojiCatalog> {
  const [catalog, messages] = await Promise.all([
    import('./emoji/catalog'),
    language === 'fr' ? import('./emoji/messages.fr') : language === 'zh' ? import('./emoji/messages.zh') : import('./emoji/messages.en'),
  ])
  return { icons: catalog.default.icons, messages: { [language]: messages.default } }
}

// Share one deferred catalogue across tag rows. No emoji SVG files are needed.
export async function loadTagEmojiIcons(install: (locale: string, messages: TagEmojiMessages) => void, family: Family = 'emoji', locale = 'en'): Promise<TagEmojiIcon[]> {
  const language = locale.startsWith('fr') ? 'fr' : locale.startsWith('zh') ? 'zh' : 'en'
  const key = family === 'emoji' ? `emoji:${language}` : family
  if (!catalogPromises.has(key)) {
    const request = family === 'emoji' ? unicodeCatalog(language) : (family === 'mdi' ? import('./emoji/mdi') : import('./emoji/awesome')).then(module => module.default)
    catalogPromises.set(key, request.catch((error: unknown) => { catalogPromises.delete(key); throw error }))
  }
  const catalog = await catalogPromises.get(key)!
  if (!installed.has(key)) {
    for (const [locale, messages] of Object.entries(catalog.messages)) install(locale, messages)
    installed.add(key)
  }
  return catalog.icons
}
