// Reusable utility components.
import { defineAsyncComponent } from 'vue'
import { defineAsyncView } from './asyncView'
export { defineAsyncView } from './asyncView'
export { ResourceDetailDialog, preloadResourceDetail } from './resourceDetail'
export type { ResourceDetailTarget } from './resourceDetail'
export { default as ConversationTurnDialog } from './components/ConversationTurnDialog.vue'
import './resourcePreviewCard.css'
export { showConfirmationDialog } from './confirmationDialog'
export { startVisiblePolling } from './visiblePolling'
export { isPrivateHostname } from './networkAddress'
export { applyDocumentContrast } from './documentContrast'
export { default as NetworkAccessNotice } from './components/NetworkAccessNotice.vue'
export const CodeEditor = defineAsyncView(() => import('./components/CodeEditor.vue'))
export { default as ResourceAttachments } from './components/ResourceAttachments.vue'
export { default as RenameFileButton } from './components/RenameFileButton.vue'
export type { AttachmentSource, ResourceAttachment } from './resourceAttachments'
export { default as ExecutionDateFilters } from './components/ExecutionDateFilters.vue'
export const FullscreenPreview = defineAsyncView(() => import('./components/FullscreenPreview.vue'))
export { default as ResourcePreviewBlock } from './components/ResourcePreviewBlock.vue'
export const AudioResourcePlayer = defineAsyncView(() => import('./components/AudioResourcePlayer.vue'))
export { default as FolderIcon } from './components/FolderIcon.vue'
export { default as DocumentFileIcon } from './components/DocumentFileIcon.vue'
export { folderArtwork } from './folderArtwork'
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
export { default as GraphViewControls } from './components/GraphViewControls.vue'
export { default as ContextHelp } from './components/ContextHelp.vue'
export { contextHelpKey, type ContextHelpState } from './contextHelp'
export { default as StatusBadge } from './components/StatusBadge.vue'
export { default as TileTexture } from './components/TileTexture.vue'
export { default as WorkingDocumentEditor } from './components/WorkingDocumentEditor.vue'
export { default as WorkingDocumentDialog } from './components/WorkingDocumentDialog.vue'
export { documentNavigationKey } from './documentNavigation'
export { useDocumentHistory } from './documentHistory'
export { default as DocumentNavigationButtons } from './components/DocumentNavigationButtons.vue'
export { resolveWorkingDocument } from './workingDocumentEditor'
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
  documentIdFromResourceUri,
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
export type { EditorVoiceControls } from './editorVoice'
export type { EditorVoiceContext, EditorVoiceSession, EditorVoiceProvider } from './editorVoice'
export const RichText = defineAsyncView(() => import('./components/RichText.vue'))
export const EditorialContent = defineAsyncView(() => import('./components/EditorialContent.vue'))
export { attachmentReference, richTextExcerpt, richLinkHref, searchRichLinks, type RichContentContribution } from './richText'
export { richLinkTarget, richLinkCard } from './richText'
export { ResourceThumbnail, DocumentResourceReferences } from './resourceContributions'
export { documentResourceHtml } from './documentResources'
export { formatFileSize, sizeInMegabytes, sizeFromMegabytes } from './fileSize'
export type { FileSizeUnit } from './fileSize'
export { default as PersonAvatar } from './components/PersonAvatar.vue'
export { default as ConversationBubble } from './components/ConversationBubble.vue'
export { default as WaitingResponseIndicator } from './components/WaitingResponseIndicator.vue'
export { preparePortableDocumentSnapshot } from './facade'
export { queuePreview } from './previewQueue'
export type { RegisterDocumentCapture, RenderedDocumentCapture } from './renderedDocument'
export { captureElementRendering } from './captureElementRendering'
