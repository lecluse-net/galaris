// Bootstrap consumers share the public primitives without importing the component catalogue.
import { defineAsyncView } from './asyncView'

export const DocumentLink = /* @__PURE__ */ defineAsyncView(() => import('./components/DocumentLink.vue'))
export const DocumentCard = /* @__PURE__ */ defineAsyncView(() => import('./components/DocumentCard.vue'))
export const DocumentEmbed = /* @__PURE__ */ defineAsyncView(() => import('./components/DocumentEmbed.vue'))
export const DocumentToolbar = /* @__PURE__ */ defineAsyncView(() => import('./components/DocumentToolbar.vue'))
export const DocumentToolbarFrame = /* @__PURE__ */ defineAsyncView(() => import('./components/DocumentToolbarFrame.vue'))
export const DocumentToolbarNavigation = /* @__PURE__ */ defineAsyncView(() => import('./components/DocumentToolbarNavigation.vue'))
export { registerDocumentFullscreenToolbarKey } from './documentFullscreen'
export const DocumentPdfShareDialog = /* @__PURE__ */ defineAsyncView(() => import('./components/DocumentPdfShareDialog.vue'))
export type { DocumentToolbarCommand, DocumentToolbarGroup } from './documentToolbar'
export type { RenderedDocumentResolver } from './renderedDocument'
export { groupMemberOptions } from './groupMemberOptions'
export type { MemberChoice, MemberTeam, MemberTeams } from './groupMemberOptions'
export { usePersonMemberships } from './personMemberships'
export { createSessionReadCache, createSessionResponseCache, invalidateSessionReads, onSessionReadInvalidation } from './sessionReadCache'
export { createSessionCatalogueCache, invalidateSessionImages, readSessionImage, onReadSessionChanged } from './sessionResources'
export { queuePreview } from './previewQueue'
export { saveBlobAsResource } from './resourceViewer'
export { createEditorialMatcher } from './editorialSearch'
export { normalizedTagIcon, unicodeIcon } from './tagIcon'
export { withAttachmentInventory, type DocumentResource } from './documentResources'

export async function printStaticDocument(...args: Parameters<typeof import('./printDocument').printStaticDocument>): Promise<void> {
  const { printStaticDocument: print } = await import('./printDocument')
  await print(...args)
}
export { attachmentReference } from './documentResource'
export { resourceBlock, resourceLinkElement, explicitReferenceMode, providerImageReference, referenceMode } from './documentReference'
export { referenceUri, validReferenceAttribute } from './documentReference'
export { documentReferenceCards, writeDocumentEmbedSize, type DocumentEmbedSize,
  type DocumentReferenceAction, type RegisterDocumentReferenceActions, type DocumentReferenceMode } from './documentReference'
export { provideDocumentReferencePath, useDocumentReferencePath } from './documentReferencePath'
export { canonicalResourceLink } from './resourceUri'
export { thumbnailReady, onThumbnailReady } from './resourceThumbnailEvents'
export type { ResourceThumbnailReady } from './resourceThumbnailEvents'
export { contextHelpKey } from './contextHelp'
export { showConfirmationDialog } from './confirmationDialog'
export { default as DialogHeader } from './components/DialogHeader.vue'
export { default as ContextSubmenu } from './components/ContextSubmenu.vue'
export { default as PersonAvatar } from './components/PersonAvatar.vue'
export { solaireCss } from './solaireTheme'
export { referenceId, referenceCardHtml, referenceDate, referenceStatus } from './resourceReference'
export { documentIdFromResourceUri, documentUriFromLink } from './documentResource'
export { documentFolderId, documentFolderHref, canonicalFolderLink } from './documentFolderResource'
export { browserResourceKind } from './resourceViewer'
export { registerResourceViewer, findResourceViewer } from './resourceViewers'
export type { ResourceViewerContribution, ResourceViewerSource } from './resourceViewers'
export { defineAsyncView }
export { startVisiblePolling } from './visiblePolling'
export { withSessionScope, storeRequests, storeRequestFailure } from './sessionStore'

/** Keep document export independent of the utility component catalogue. */
export async function preparePortableDocumentSnapshot(...args: Parameters<typeof import('./documentSnapshot').preparePortableDocumentSnapshot>): Promise<string> {
  const snapshot = await import('./documentSnapshot')
  return snapshot.preparePortableDocumentSnapshot(...args)
}
export async function downloadDocumentBundle(...args: Parameters<typeof import('./exportDocumentBundle').downloadDocumentBundle>): Promise<void> {
  const { downloadDocumentBundle: download } = await import('./exportDocumentBundle')
  await download(...args)
}
export async function createDocumentPdf(...args: Parameters<typeof import('./exportDocumentPdf').createDocumentPdf>): Promise<File> {
  const { createDocumentPdf: create } = await import('./exportDocumentPdf')
  return create(...args)
}
export { solaire } from './solaire'
export { solaireColors } from './solaire'
export { mountImageResize } from './imageResize'
