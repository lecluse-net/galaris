const emojiMarkerPattern = /[\p{Extended_Pictographic}\p{Emoji_Presentation}\p{Regional_Indicator}\u20e3]/u
let segmenter: Intl.Segmenter | undefined

/** Decorate graphemes while keeping ordinary prose in contiguous text nodes. */
export function enlargeMessageEmojis(root: HTMLElement): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node): number {
      if (!node.textContent || !emojiMarkerPattern.test(node.textContent)
        || node.parentElement?.closest('code, pre, textarea, .chat-message-emoji')) {
        return NodeFilter.FILTER_REJECT
      }
      return NodeFilter.FILTER_ACCEPT
    },
  })
  const textNodes: Text[] = []
  let current = walker.nextNode()
  while (current) {
    if (current instanceof Text) textNodes.push(current)
    current = walker.nextNode()
  }

  for (const textNode of textNodes) {
    segmenter ??= new Intl.Segmenter(undefined, { granularity: 'grapheme' })
    const text = textNode.data
    const segments = segmenter.segment(text)
    const fragment = document.createDocumentFragment()
    let cursor = 0
    for (const match of text.matchAll(new RegExp(emojiMarkerPattern.source, 'gu'))) {
      const grapheme = segments.containing(match.index)
      if (!grapheme || grapheme.index < cursor) continue
      const { segment, index } = grapheme
      if (index > cursor) fragment.append(document.createTextNode(text.slice(cursor, index)))
      const emoji = document.createElement('span')
      emoji.className = 'chat-message-emoji'
      emoji.textContent = segment
      fragment.append(emoji)
      cursor = index + segment.length
    }
    if (cursor < text.length) fragment.append(document.createTextNode(text.slice(cursor)))
    textNode.replaceWith(fragment)
  }
}
