import type { MemoryRankedItem } from '../types'


export function excludeMemorySearchResults(
  results: MemoryRankedItem[],
  excludedItemIds: ReadonlySet<string>,
): MemoryRankedItem[] {
  return results.filter(item => !excludedItemIds.has(item.id))
}
