export interface ResourceThumbnailReady {
  agentId: number | null
  itemId?: string
  resourceUri?: string
  blob: Blob
}

const listeners = new Set<(thumbnail: ResourceThumbnailReady) => void>()

/** Share authorized preview arrivals with mounted views, without retaining bytes. */
export function thumbnailReady(thumbnail: ResourceThumbnailReady): void {
  for (const listener of listeners) listener(thumbnail)
}

export function onThumbnailReady(listener: (thumbnail: ResourceThumbnailReady) => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
