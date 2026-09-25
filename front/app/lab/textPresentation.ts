import { richTextExcerpt } from '@/core/util'

/** A text-only preview; the original benchmark input remains untouched. */
export function labPreviewText(value: unknown): string {
  const plain = (text: string) => richTextExcerpt(text).replace(/\s+/g, ' ').trim()
  const text = typeof value === 'string'
    ? plain(value)
    : JSON.stringify(value ?? null, (_key, entry: unknown) => typeof entry === 'string' ? plain(entry) : entry)
  return text.slice(0, 160)
}
