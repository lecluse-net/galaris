/** Only append new speech from cumulative audio snapshots, ignoring earlier revisions. */
export function transcriptSuffix(previous: string, current: string): string {
  const next = current.trim(), old = previous.trim()
  if (!next || next === old) return ''
  if (!old) return next
  if (next.startsWith(old)) return next.slice(old.length).trimStart()
  const tokens = (value: string) => [...value.matchAll(/[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu)].map(match => ({
    start: match.index, word: match[0].normalize('NFKC').toLocaleLowerCase(),
  }))
  const before = tokens(old), after = tokens(next)
  if (before.length <= after.length && before.every((token, index) => token.word === after[index]!.word)) {
    return before.length === after.length ? '' : next.slice(after[before.length]!.start)
  }
  // Locate the strongest shared phrase near the previous tail. Account for words
  // revised after that anchor so an earlier correction cannot repeat a whole sentence.
  let bestLength = 0, oldEnd = 0, nextEnd = 0
  for (let left = Math.max(0, before.length - 40); left < before.length; left += 1) {
    for (let right = 0; right < after.length; right += 1) {
      let length = 0
      while (left + length < before.length && right + length < after.length
        && before[left + length]!.word === after[right + length]!.word) length += 1
      if (length > bestLength || (length === bestLength && left + length > oldEnd)) {
        bestLength = length; oldEnd = left + length; nextEnd = right + length
      }
    }
  }
  if (bestLength < 2 && (bestLength !== 1 || before[oldEnd - 1]!.word.length < 4)) return ''
  const boundary = nextEnd + before.length - oldEnd
  return boundary < after.length ? next.slice(after[boundary]!.start) : ''
}
