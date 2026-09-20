const sourceKeys: Record<string, string> = {
  nextcloud: 'nextcloudTalk',
  nextcloud_talk: 'nextcloudTalk',
  talk: 'nextcloudTalk',
  telegram: 'telegram',
  matrix: 'matrix',
  one_bot: 'oneBot',
  onebot: 'oneBot',
  whatsapp: 'whatsApp',
}

export function sourceTranslationKey(source: string): string {
  const normalized = source.trim().toLowerCase()
  return `chat.sources.${sourceKeys[normalized] ?? 'other'}`
}
