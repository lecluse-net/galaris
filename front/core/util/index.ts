// Reusable utility components.
import { defineAsyncComponent } from 'vue'
import { defineAsyncView } from './asyncView'
export { defineAsyncView } from './asyncView'
import './resourcePreviewCard.css'
export { showConfirmationDialog } from './confirmationDialog'
export { startVisiblePolling } from './visiblePolling'
export const CodeEditor = defineAsyncView(() => import('./components/CodeEditor.vue'))
export { default as ExecutionDateFilters } from './components/ExecutionDateFilters.vue'
export const FullscreenPreview = defineAsyncView(() => import('./components/FullscreenPreview.vue'))
export { default as ResourcePreviewBlock } from './components/ResourcePreviewBlock.vue'
export const AudioResourcePlayer = defineAsyncView(() => import('./components/AudioResourcePlayer.vue'))
export { default as FolderIcon } from './components/FolderIcon.vue'
export { solaire, solaireColors, type SolaireColor } from './solaire'
export { solaireCss } from './solaireTheme'
export const Model3dThumbnail = defineAsyncView(() => import('./components/Model3dThumbnail.vue'))
export const Model3dViewer = defineAsyncView(() => import('./components/Model3dViewer.vue'))
export { model3dFormat } from './model3d'
export type { Model3dSource } from './model3d'
export const HtmlPreview = defineAsyncView(() => import('./components/HtmlPreview.vue'))
// Backward-compatible alias.
export const JsonEditor = CodeEditor
export const Markdown = defineAsyncView(() => import('./components/Markdown.vue'))
export const TextResourcePreview = defineAsyncView(() => import('./components/TextResourcePreview.vue'))
export const MarkdownWysiwygEditor = defineAsyncView(() => import('./components/MarkdownWysiwygEditor.vue'))
export { default as PageHeader } from './components/PageHeader.vue'
export { default as ContextHelp } from './components/ContextHelp.vue'
export { contextHelpKey, type ContextHelpState } from './contextHelp'
export { default as StatusBadge } from './components/StatusBadge.vue'
export { default as TileTexture } from './components/TileTexture.vue'
export { default as WorkingDocumentEditor } from './components/WorkingDocumentEditor.vue'
export { default as WorkingDocumentIcon } from './components/WorkingDocumentIcon.vue'
export { default as WorkingDocumentThumbnail } from './components/WorkingDocumentThumbnail.vue'
export { searchWorkingDocuments } from './workingDocumentEditor'
export type {
  WorkingDocumentReference,
  WorkingDocumentEditorContribution,
  WorkingDocumentSnapshot,
} from './workingDocumentEditor'
export {
  documentIdFromRouteQuery,
  documentResourceHref,
} from './documentResource'
export { sanitizeHtml, sanitizePreviewHtml } from './sanitizeHtml'
export {
  browserResourceKind,
  isolatedBrowserResourceUrl,
  normalizedMediaType,
  saveBlobAsResource,
  shouldOpenInline,
} from './resourceViewer'
export type { BrowserResourceKind, NavigationClick } from './resourceViewer'
export type { StatusBadgeTone } from './statusBadge'
// Reading a document or using a utility must not initialize the editing engine.
export const RichTextEditor = defineAsyncComponent(() => import('./components/RichTextEditor.vue'))
export type { EditorVoiceControls } from './ckeditorVoice'
export type { EditorVoiceContext, EditorVoiceSession, EditorVoiceProvider } from './editorVoice'
export const RichText = defineAsyncView(() => import('./components/RichText.vue'))
export const EditorialContent = defineAsyncView(() => import('./components/EditorialContent.vue'))
export { attachmentReference, richTextExcerpt, richLinkHref, type RichContentContribution } from './richText'
export { documentResourceHtml } from './documentResources'
export { formatFileSize, sizeInMegabytes, sizeFromMegabytes } from './fileSize'
export type { FileSizeUnit } from './fileSize'
export const SharingPanel = defineAsyncView(() => import('./components/SharingPanel.vue'))
export { default as PersonAvatar } from './components/PersonAvatar.vue'
export type { SharingDraft, SharingLevel, SharingRecipient, SharingState } from './sharing'
export { preparePortableDocumentSnapshot } from './facade'
export { queuePreview } from './previewQueue'
export type { RegisterDocumentCapture, RenderedDocumentCapture } from './renderedDocument'
