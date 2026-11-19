/** Literal matching shared by independent editorial surfaces. Ranges are DOM offsets. */
export function createEditorialMatcher(query: string, matchCase: boolean, wholeWords: boolean) {
  const expression = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), matchCase ? 'gu' : 'giu')
  return (text: string): Array<{ from: number; to: number }> => {
    const ranges: Array<{ from: number; to: number }> = []
    if (!query) return ranges
    for (const match of text.matchAll(expression)) {
      const from = match.index, to = from + match[0].length
      if (wholeWords && (/[\p{L}\p{N}_]$/u.test(text.slice(0, from)) || /^[\p{L}\p{N}_]/u.test(text.slice(to)))) continue
      ranges.push({ from, to })
    }
    return ranges
  }
}
