export { createSessionReadCache, createSessionResponseCache, invalidateSessionReads, onSessionReadInvalidation } from './sessionReadCache'
export { queuePreview } from './previewQueue'

/** Keep document export independent of the utility component catalogue. */
export async function preparePortableDocumentSnapshot(...args: Parameters<typeof import('./documentSnapshot').preparePortableDocumentSnapshot>): Promise<string> {
  const snapshot = await import('./documentSnapshot')
  return snapshot.preparePortableDocumentSnapshot(...args)
}
