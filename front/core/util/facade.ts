// Bootstrap consumers share the public primitives without importing the component catalogue.
export { createSessionReadCache, createSessionResponseCache, invalidateSessionReads, onSessionReadInvalidation } from './sessionReadCache'
export { createSessionCatalogueCache, createSessionImageCache, onReadSessionChanged } from './sessionResources'
export { queuePreview } from './previewQueue'
export { saveBlobAsResource } from './resourceViewer'
export { attachmentReference } from './richText'
export { thumbnailReady, onThumbnailReady } from './resourceThumbnailEvents'
export type { ResourceThumbnailReady } from './resourceThumbnailEvents'
export { contextHelpKey } from './contextHelp'
export { showConfirmationDialog } from './confirmationDialog'
export { default as ContextSubmenu } from './components/ContextSubmenu.vue'
export { default as PersonAvatar } from './components/PersonAvatar.vue'
export { solaireCss } from './solaireTheme'
export { referenceId, referenceCardHtml, referenceDate, referenceStatus } from './resourceReference'
export { documentIdFromResourceUri } from './documentResource'
export { documentFolderId, documentFolderHref, canonicalFolderLink } from './documentFolderResource'
export { browserResourceKind } from './resourceViewer'
export { defineAsyncView } from './asyncView'

/** Keep document export independent of the utility component catalogue. */
export async function preparePortableDocumentSnapshot(...args: Parameters<typeof import('./documentSnapshot').preparePortableDocumentSnapshot>): Promise<string> {
  const snapshot = await import('./documentSnapshot')
  return snapshot.preparePortableDocumentSnapshot(...args)
}
