import { defineAsyncComponent } from 'vue'

export const DocumentEditor = defineAsyncComponent(() => import('./components/DocumentEditor.vue'))
export const DocumentSharingPanel = defineAsyncComponent(() => import('./components/DocumentSharingPanel.vue'))
export const DocumentAttachments = defineAsyncComponent(() => import('./components/DocumentAttachments.vue'))
export const DocumentDialog = defineAsyncComponent(() => import('./components/DocumentDialog.vue'))
export const DocumentIcon = defineAsyncComponent(() => import('./components/DocumentIcon.vue'))
export const DocumentThumbnail = defineAsyncComponent(() => import('./components/DocumentThumbnail.vue'))
export const DocumentFolderCollection = defineAsyncComponent(() => import('./components/DocumentFolderCollection.vue'))
export const DocumentFolderThumbnail = defineAsyncComponent(() => import('./components/DocumentFolderThumbnail.vue'))
export { documentService, DatasetDocumentRedirect } from './services/documentService'
export type * from './types'
