export interface MemoryThumbnailReady {
  agentId: number | null
  itemId?: string
  resourceUri?: string
  blob: Blob
}

const listeners = new Set<(thumbnail: MemoryThumbnailReady) => void>()

/** Share authorized preview arrivals with mounted views, without retaining bytes. */
export function thumbnailReady(thumbnail: MemoryThumbnailReady): void {
  for (const listener of listeners) listener(thumbnail)
}

export function onThumbnailReady(listener: (thumbnail: MemoryThumbnailReady) => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
