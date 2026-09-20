export type TagFontFamily = 'mdi' | 'awesome'
const fonts: Partial<Record<TagFontFamily, Promise<void>>> = {}

export function loadTagFont(family: TagFontFamily): Promise<void> {
  return fonts[family] ??= (async () => {
    if (family === 'mdi') await import('@quasar/extras/mdi-v7/mdi-v7.css')
    else await import('@quasar/extras/fontawesome-v7/fontawesome-v7.css')
  })().catch((error: unknown) => { delete fonts[family]; throw error })
}

export function normalizedTagIcon(value: string | null | undefined): string {
  const legacy = value?.match(/^\/tag-icons\/(?:openmoji|fluent)\/([0-9A-F-]+)\.svg$/)
  return legacy ? `emoji:${legacy[1]!.split('-').filter(code => code !== 'FE0F').join('-')}` : (value ?? '')
}

export function unicodeIcon(value: string): string {
  if (!/^emoji:[0-9A-F]+(?:-[0-9A-F]+)*$/.test(value)) return ''
  try {
    return value.slice(6).split('-').map(code => String.fromCodePoint(Number.parseInt(code, 16)))
      .map(character => /\p{Emoji}/u.test(character) && !/\p{Emoji_Presentation}/u.test(character) ? `${character}\uFE0F` : character).join('')
  } catch { return '' }
}
