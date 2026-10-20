export { createSessionReadCache, createSessionResponseCache, invalidateSessionReads, onSessionReadInvalidation } from './sessionReadCache'
export { createSessionCatalogueCache, createSessionImageCache, onReadSessionChanged } from './sessionResources'
export { queuePreview } from './previewQueue'
export { saveBlobAsResource } from './resourceViewer'
export { attachmentReference } from './richText'

/** Keep document export independent of the utility component catalogue. */
export async function preparePortableDocumentSnapshot(...args: Parameters<typeof import('./documentSnapshot').preparePortableDocumentSnapshot>): Promise<string> {
  const snapshot = await import('./documentSnapshot')
  return snapshot.preparePortableDocumentSnapshot(...args)
}
