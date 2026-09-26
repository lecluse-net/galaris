<template>
  <div class="ck-galaris-editor" :style="{ '--editor-min-height': minHeight, '--editor-max-height': autoGrow ? 'none' : maxHeight }">
    <Ckeditor :key="profile + ':' + locale" :editor="ClassicEditor" :config="config" :model-value="editorData" :disabled="readonly" :disable-two-way-data-binding="true" @ready="ready" />
    <Teleport v-for="target in embeddedTargets" :key="target.key" :to="target.element">
      <slot name="embedded-code" :source="target.source" :language="target.language" :register-snapshot="(capture: RenderedDocumentCapture | undefined) => registerSnapshot(target.key, capture)"><div class="q-pa-md">{{ t('richEditor.embeddedApplication') }}</div></slot>
    </Teleport>
    <audio v-if="personalVoice" ref="playbackElement" hidden />
    <div v-if="personalVoice?.error.value" role="alert" class="q-pa-sm">{{ personalVoice.error.value }}</div>
    <div v-if="fileUploadProgress" class="row items-center q-gutter-sm q-pa-sm" role="status">
      <q-linear-progress class="col" :value="fileUploadProgress.progress" />
      <span class="text-caption">{{ fileUploadProgress.name }} · {{ Math.round(fileUploadProgress.progress * 100) }}% · {{ fileUploadProgress.index }}/{{ fileUploadProgress.total }}</span>
      <q-btn flat round dense icon="close" :aria-label="t('richEditor.resources.cancelUpload')" @click="cancelFileUpload?.()"><q-tooltip>{{ t('richEditor.resources.cancelUpload') }}</q-tooltip></q-btn>
    </div>
    <div v-if="importingHtml" role="status" class="row items-center q-gutter-sm q-pa-sm">
      <q-spinner /><span>{{ t('richEditor.resources.importingHtml') }}</span>
      <q-btn flat round dense icon="close" :aria-label="t('common.cancel')" @click="importRequest?.abort()" />
    </div>
    <GalarisLinkDialog v-model="linkOpen" :initial-label="linkLabel" @insert="insertGalarisLink" @hide="editor?.editing.view.focus()" />
    <PdfPreview v-model="pdfPreview" />
    <q-dialog v-model="shareOpen" @hide="cancelDocumentShare">
      <q-card style="width: 420px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center"><div class="text-h6">{{ t('richEditor.share.title') }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section>
        <q-card-section>
          <div v-if="sharePreparing" role="status" class="row items-center q-gutter-sm"><q-spinner /><span>{{ t('richEditor.share.preparing') }}</span></div>
          <div v-else-if="shareError" role="alert">{{ shareError }}</div>
          <div v-else-if="shareFile">{{ shareFile.name }}</div>
        </q-card-section>
        <q-card-actions align="right"><q-btn v-close-popup flat :label="t('common.cancel')" /><q-btn v-if="shareError && !shareFile" flat :label="t('common.retry')" @click="prepareDocumentShare" /><q-btn v-else color="primary" :disable="!shareFile" :loading="sharing" :label="t(nativeShareData ? 'richEditor.share.action' : 'richEditor.share.save')" @click="shareDocument" /></q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, useSlots, useTemplateRef, watch } from 'vue'
import { useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { Ckeditor } from '@ckeditor/ckeditor5-vue'
import {
  ClassicEditor, Essentials, Paragraph, Heading, Bold, Italic, Underline, Strikethrough, Subscript, Superscript, Code,
  Link, List, ListProperties, Indent, IndentBlock, BlockQuote, CodeBlock, HorizontalLine, Alignment, Highlight,
  FontFamily, FontSize, FontColor, FontBackgroundColor, FindAndReplace, RemoveFormat, SelectAll, SpecialCharacters,
  SpecialCharactersEssentials, SourceEditing, Fullscreen, GeneralHtmlSupport, PasteFromOffice, Style,
  Table, TableToolbar, TableProperties, TableCellProperties, TableColumnResize, TableCaption,
  Image, ImageCaption, ImageStyle, ImageToolbar, ImageResize, ImageUpload, ImageUtils, LinkImage,
  Plugin, LinkUI, ButtonView, DropdownView, ContextualBalloon, IconBrowseFiles, IconBoxWithMarker, ModelLiveRange, type ModelSelection, type LinkPreviewButtonNavigateEvent, type EditorConfig, type Editor,
} from 'ckeditor5'
import fr from 'ckeditor5/translations/fr.js'
import zh from 'ckeditor5/translations/zh-cn.js'
import { marked } from 'marked'
import { richLinkHref, sanitizeRichHtml, validRichLink, type ContentProfile } from '../richText'
import { attachDocumentImages } from '../ckeditorAttachments'
import { pasteDocumentHtml } from '../pasteDocumentHtml'
import { pastedMarkdownHtml } from '../pasteMarkdown'
import { attachDocumentFileUpload, type DocumentUploadProgress } from '../ckeditorFileUpload'
import PdfPreview from './PdfPreview.vue'
import type { PdfPreviewSource } from '../documentMedia'
import { attachCalloutStyles, calloutKinds } from '../ckeditorCallouts'
import { attachGnomeEditorIcons, gnomeEditorIcon } from '../ckeditorIcons'
import { GalarisSourceEditing } from '../ckeditorSourceEditing'
import { GalarisCodeHighlight } from '../ckeditorCodeHighlight'
import { attachCodeTools, codeBlockLanguages } from '../ckeditorCodeTools'
import { attachEditorToolbarGroups, editorToolbarCommands, editorToolbarGroups, registerEditorToolbarGroups } from '../ckeditorToolbar'
import { registerEditorVoice } from '../ckeditorVoice'
import { editorVoiceProvider } from '../editorVoice'
import { attachLinkCards } from '../ckeditorLinkCards'
import { attachDocumentPlayers } from '../ckeditorDocumentPlayers'
import { attachEmbeddedCode, type EmbeddedCodeTarget } from '../ckeditorEmbeddedCode'
import { protectInteractiveHtml, restoreInteractiveHtml } from '../interactiveHtml'
import { withAttachmentInventory, type DocumentResource } from '../documentResources'
import { exportDocumentBundle } from '../exportDocumentBundle'
import bootstrapZipIcon from '../icons/bootstrap/file-zip-fill.svg?raw'
import { solaireCss as solaire } from '../solaireTheme'
const documentArchiveIcon = bootstrapZipIcon.replaceAll('<path ', `<path style="fill: ${solaire.blue.accent}" `)
import { attachmentReference } from '../richText'
import GalarisLinkDialog from './GalarisLinkDialog.vue'
import { printDocument } from '../printDocument'
import type { RenderedDocumentCapture, RenderedDocumentResolver } from '../renderedDocument'
import { createDocumentPdf, exportDocumentPdf } from '../exportDocumentPdf'
import { saveBlobAsResource } from '../resourceViewer'
import '../ckeditorTheme.css'
const { modelValue, mediaType = 'text/html', profile = 'rich-text', readonly = false, minHeight = '240px', maxHeight = '70vh', autoGrow = false, ariaLabel = '', documentTitle = '', documentUrl = '', exportPdf, exportBundle, uploadImage, uploadFile, importImage, resolveImage, attachments = [], createLinkCard, manageAttachments = false } = defineProps<{
  modelValue: string; mediaType?: string; profile?: ContentProfile; readonly?: boolean; minHeight?: string; maxHeight?: string; autoGrow?: boolean; ariaLabel?: string
  attachments?: DocumentResource[]
  manageAttachments?: boolean
  createLinkCard?: (url: string) => Promise<string>
  exportBundle?: (html: string, signal: AbortSignal) => Promise<Blob>
  uploadFile?: (file: File, signal: AbortSignal, progress: (value: number) => void) => Promise<string>
  documentTitle?: string
  documentUrl?: string
  exportPdf?: (html: string, signal: AbortSignal) => Promise<Blob>
  uploadImage?: (file: File, signal: AbortSignal, progress: (value: number) => void) => Promise<string>
  importImage?: (url: string, signal: AbortSignal) => Promise<string>
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>
}>()
const emit = defineEmits<{ 'manage-attachments': []; 'update:modelValue': [value: string]; 'open-attachment': [documentId: string, attachmentId: string] }>()
const { t, locale } = useI18n()
const $q = useQuasar()
const editor = shallowRef<ClassicEditor>()
const embeddedTargets = shallowRef<EmbeddedCodeTarget[]>([])
const captures = new Map<number, RenderedDocumentCapture>()
const slots = useSlots()
function registerSnapshot(key: number, capture: RenderedDocumentCapture | undefined): void {
  if (capture) captures.set(key, capture)
  else captures.delete(key)
}
const captureRenderedContent: RenderedDocumentResolver = async (source, language, index, signal) => {
  const targets = [...embeddedTargets.value].sort((a, b) => a.element.compareDocumentPosition(b.element) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1)
  const target = targets[index]
  const capture = target && captures.get(target.key)
  if (!target || target.source !== source || target.language !== language || !capture) throw new Error('Current document rendering unavailable')
  return capture(signal)
}
const resolveRenderedContent = computed(() => slots['embedded-code'] ? captureRenderedContent : undefined)
const documentLayout = ref<'fixed' | 'full'>('fixed')
const documentFitsFixedWidth = ref(true)
const effectiveDocumentLayout = computed(() => documentFitsFixedWidth.value ? documentLayout.value : 'full')
const importingHtml = ref(false)
let importRequest: AbortController | undefined
let resourceSelection: ModelSelection | undefined
const linkOpen = ref(false), linkLabel = ref('')
const pdfPreview = shallowRef<PdfPreviewSource | null>(null)
const shareOpen = ref(false), sharePreparing = ref(false), sharing = ref(false), shareError = ref('')
const shareFile = shallowRef<File | null>(null)
let shareRequest: AbortController | undefined
const nativeShareData = computed<ShareData | null>(() => {
  if (!shareFile.value || typeof navigator.share !== 'function' || typeof navigator.canShare !== 'function') return null
  const files = [shareFile.value]
  const combined = { files, title: documentTitle, ...(documentUrl ? { url: documentUrl } : {}) }
  if (navigator.canShare(combined)) return combined
  const withText = { files, title: documentTitle, ...(documentUrl ? { text: documentUrl } : {}) }
  if (navigator.canShare(withText)) return withText
  if (navigator.canShare({ files })) return { files }
  return null
})
const fileUploadProgress = shallowRef<DocumentUploadProgress | null>(null)
let cancelFileUpload: (() => void) | undefined
let printing: AbortController | undefined
let exportingPdf: AbortController | undefined
let exportingBundle: AbortController | undefined
let linkSelection: ModelSelection | undefined
let applyingExternal = false, lastEmitted = modelValue, lastEditorData = ''
function sourceHtml(value: string): string {
  if (mediaType === 'text/markdown') return sanitizeRichHtml(marked.parse(value, { async: false }), profile)
  if (mediaType === 'text/plain') { const p = document.createElement('p'); p.textContent = value; return p.outerHTML }
  return sanitizeRichHtml(profile === 'document' ? protectInteractiveHtml(value) : value, profile)
}
const editorData = ref(sourceHtml(modelValue))
const playbackElement = useTemplateRef<HTMLAudioElement>('playbackElement')
const personalVoice = editorVoiceProvider?.({
  html: () => editor.value?.getData() ?? editorData.value,
  editable: () => !readonly,
  playbackElement: () => playbackElement.value ?? undefined,
  insert: insertDictation,
})
class GalarisIntegration extends Plugin {
  static get pluginName() { return 'GalarisIntegration' as const }
  init(): void {
    if (profile === 'document' && createLinkCard) attachLinkCards(this.editor, url => createLinkCard(url), t, () => $q.notify({ type: 'warning', message: t('richEditor.resources.cardUnavailable') }))
    const current = this.editor
    attachEmbeddedCode(current, ['galaris-app', 'galaris-raw-html'], t('richEditor.embeddedApplication'), targets => { embeddedTargets.value = targets })
    if (profile === 'document') current.data.on('get', event => { if (typeof event.return === 'string') event.return = restoreInteractiveHtml(event.return) }, { priority: 'lowest' })
    if (profile === 'document') current.ui.componentFactory.add('documentImagePreview', locale => {
      const button = new ButtonView(locale)
      const reference = () => {
        const image = current.plugins.get(ImageUtils).getClosestSelectedImageElement(current.model.document.selection)
        return attachmentReference(String(image?.getAttribute('src') ?? ''))
      }
      const update = () => { button.isEnabled = Boolean(reference()) }
      button.set({ label: t('richEditor.resources.openImage'), icon: gnomeEditorIcon('view-fullscreen'), tooltip: true })
      button.listenTo(current.model.document.selection, 'change', update)
      button.listenTo(current.model.document, 'change:data', update)
      update()
      button.on('execute', () => {
        const attachment = reference()
        if (attachment) emit('open-attachment', ...attachment)
      })
      return button
    })
    if (profile === 'document') cancelFileUpload = attachDocumentFileUpload(current, {
      upload: uploadFile, translate: t,
      progress: value => { fileUploadProgress.value = value },
      failed: name => $q.notify({ type: 'negative', message: t('richEditor.resources.uploadFailed', { name }) }),
    })
    if (profile === 'document') attachDocumentPlayers(current, (documentId, attachmentId) => resolveImage?.(documentId, attachmentId), () => attachments, t, source => { pdfPreview.value = source })
    attachCalloutStyles(current)
    attachCodeTools(current, t, success => $q.notify({ type: success ? 'positive' : 'negative', message: t('richEditor.codeTools.' + (success ? 'copied' : 'copyFailed')) }))
    if (profile === 'document') current.ui.componentFactory.add('documentLayout', locale => {
      const button = new ButtonView(locale)
      button.set({ label: t('richEditor.layout.full'), icon: gnomeEditorIcon('stock_zoom-page-width'), withText: false, isToggleable: true })
      const update = () => button.set({
        isOn: effectiveDocumentLayout.value === 'full',
        isEnabled: documentFitsFixedWidth.value,
        tooltip: t('richEditor.layout.' + (documentFitsFixedWidth.value && effectiveDocumentLayout.value === 'full' ? 'fixed' : 'full')),
      })
      update()
      const stop = watch([effectiveDocumentLayout, documentFitsFixedWidth], () => {
        applyDocumentLayout(current)
        update()
      })
      current.on('destroy', stop)
      button.on('execute', () => {
        documentLayout.value = documentLayout.value === 'fixed' ? 'full' : 'fixed'
        applyDocumentLayout(current)
        update()
      })
      return button
    })
    if (profile === 'document') current.ui.componentFactory.add('documentPrint', locale => {
      const button = new ButtonView(locale)
      button.set({ label: t('richEditor.print'), icon: gnomeEditorIcon('document-print'), tooltip: true })
      button.on('execute', () => {
        printing?.abort()
        const request = new AbortController()
        printing = request
        button.isEnabled = false
        void printDocument(current.getData(), documentTitle || ariaLabel || t('richEditor.content'), request.signal, resolveImage, resolveRenderedContent.value)
          .catch(() => { if (!request.signal.aborted) $q.notify({ type: 'negative', message: t('richEditor.printFailed') }) })
          .finally(() => { if (editor.value === current && printing === request) button.isEnabled = true })
      })
      return button
    })
    if (profile === 'document') current.ui.componentFactory.add('documentShare', locale => {
      const button = new ButtonView(locale)
      button.set({ label: t('richEditor.share.action'), tooltip: true, isEnabled: Boolean(exportPdf), icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="m7 11 10-6m-10 8 10 6" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="5" cy="12" r="3"/><circle cx="18" cy="4" r="3"/><circle cx="18" cy="20" r="3"/></svg>' })
      button.on('execute', () => { void prepareDocumentShare() })
      return button
    })
    if (profile === 'document') current.ui.componentFactory.add('documentExportPdf', locale => {
      const button = new ButtonView(locale)
      button.set({
        label: t('richEditor.exportPdf'), tooltip: true, isEnabled: Boolean(exportPdf),
      })
      button.on('execute', () => {
        if (!exportPdf) return
        exportingPdf?.abort()
        const request = new AbortController()
        exportingPdf = request
        button.isEnabled = false
        void exportDocumentPdf(current.getData(), documentTitle || ariaLabel || t('richEditor.content'), request.signal, exportPdf, resolveImage, resolveRenderedContent.value)
          .catch(() => { if (!request.signal.aborted) $q.notify({ type: 'negative', message: t('richEditor.exportPdfFailed') }) })
          .finally(() => { if (editor.value === current && exportingPdf === request) button.isEnabled = Boolean(exportPdf) })
      })
      return button
    })
    if (profile === 'document') {
      for (const [name, icon, action] of [
        ['documentAttachments', gnomeEditorIcon('document-open'), () => { resourceSelection = current.model.createSelection(current.model.document.selection); emit('manage-attachments') }],
        ['documentExportBundle', documentArchiveIcon, () => {
          if (!exportBundle) return
          exportingBundle?.abort(); const request = new AbortController(); exportingBundle = request
          return exportDocumentBundle(withAttachmentInventory(current.getData(), attachments, t('richEditor.resources.attachments')), documentTitle, request.signal, exportBundle, resolveImage, resolveRenderedContent.value)
            .catch(() => { if (!request.signal.aborted) $q.notify({ type: 'negative', message: t('richEditor.resources.exportFailed') }) })
        }],
      ] as const) current.ui.componentFactory.add(name, locale => {
        const button = new ButtonView(locale)
        button.set({ label: t('richEditor.resources.' + name), icon, tooltip: true })
        if (name === 'documentAttachments') button.isEnabled = manageAttachments
        if (name === 'documentExportBundle') button.isEnabled = Boolean(exportBundle)
        button.on('execute', () => {
          const result = action()
          if (result instanceof Promise) {
            button.isEnabled = false
            void result.finally(() => { if (editor.value === current) button.isEnabled = Boolean(exportBundle) })
          }
        })
        return button
      })
    }
    current.ui.componentFactory.add('galarisLink', locale => {
      const button = new ButtonView(locale)
      button.set({ label: t('richEditor.galarisLink'), icon: IconBrowseFiles, withText: false, tooltip: true })
      button.bind('isEnabled').to(current.commands.get('link')!, 'isEnabled')
      button.on('execute', openGalarisLinks)
      return button
    })
    current.conversion.for('editingDowncast').attributeToElement({
      model: 'linkHref',
      view: (value, { writer }) => {
        const uri = String(value)
        const element = writer.createAttributeElement('a', { href: richLinkHref(uri) ?? '', 'data-rich-reference': uri, target: '_blank', rel: 'noopener noreferrer' }, { priority: 5 })
        writer.setCustomProperty('link', true, element)
        return element
      },
      converterPriority: 'high',
    })
    // HTML entering through paste, drag/drop or source mode uses the storage contract.
    current.editing.view.document.on('clipboardInput', (event, data) => {
      if (current.model.document.selection.getFirstPosition()?.parent.is('element', 'codeBlock') || current.model.document.selection.hasAttribute('code')) return
      const plain = data.dataTransfer.getData('text/plain') || data.dataTransfer.getData('text/markdown')
      const text = plain.trim()
      if (!current.isReadOnly && profile === 'document' && data.method === 'paste'
        && !data.dataTransfer.files.length && /^https?:\/\/\S+$/i.test(text) && validRichLink(text)) {
        const link = document.createElement('a'); link.href = text; link.textContent = text
        data.content = current.data.processor.toView(link.outerHTML)
        return
      }
      const clipboardHtml = data.dataTransfer.getData('text/html')
      if (data.method === 'paste' && !current.isReadOnly && !data.dataTransfer.files.length) {
        const markdown = pastedMarkdownHtml(plain, clipboardHtml)
        if (markdown !== null) {
          if (profile === 'document') { event.stop(); void importHtml(markdown, current) }
          else data.content = current.data.processor.toView(sanitizeRichHtml(markdown, profile))
          return
        }
      }
      const html = clipboardHtml || plain
      if (profile === 'document' && data.method === 'paste' && !current.isReadOnly && !data.dataTransfer.files.length
        && (data.dataTransfer.getData('text/html') || /^\s*(?:<!doctype\b|<(?:html|head|body|p|div|h[1-6]|table|section|article)\b)/i.test(html))) {
        event.stop(); void importHtml(html, current); return
      }
      if (html && !data.dataTransfer.files.length) {
        const filtered = sourceHtml(html)
        data.content = current.data.processor.toView(filtered)
      }
    }, { priority: 'high' })
    current.data.on('set', (_event, args) => {
      importRequest?.abort()
      const filter = (html: string): string => {
        return sourceHtml(html)
      }
      if (typeof args[0] === 'string') args[0] = filter(args[0])
      else args[0] = Object.fromEntries(Object.entries(args[0]).map(([root, html]) => {
        if (typeof html !== 'string') throw new TypeError('Invalid editor root data')
        return [root, filter(html)]
      }))
    }, { priority: 'highest' })
    if (profile === 'document') {
      attachDocumentImages(current, {
        resolve: (documentId, attachmentId) => resolveImage?.(documentId, attachmentId),
        upload: async (file, signal, progress) => {
          if (!uploadImage || !['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.type)) throw new Error(t('richEditor.imageForbidden'))
          return uploadImage(file, signal, progress)
        },
      })
    }
    if (personalVoice) registerEditorVoice(current, () => personalVoice.controls.value)
    registerEditorToolbarGroups(current, profile === 'document', t, Boolean(personalVoice))
  }
}
const config = computed<EditorConfig>(() => ({
  licenseKey: 'GPL', language: locale.value === 'zh' ? 'zh-cn' : locale.value, translations: [fr, zh],
  plugins: [Essentials, Paragraph, Heading, Bold, Italic, Underline, Strikethrough, Subscript, Superscript, Code, Link, List, ListProperties,
    Indent, IndentBlock, BlockQuote, CodeBlock, GalarisCodeHighlight, HorizontalLine, Alignment, Highlight, FontFamily, FontSize, FontColor, FontBackgroundColor,
    FindAndReplace, RemoveFormat, SelectAll, SpecialCharacters, SpecialCharactersEssentials, SourceEditing, GalarisSourceEditing, Fullscreen, GeneralHtmlSupport, PasteFromOffice, Style,
    Table, TableToolbar, TableProperties, TableCellProperties, TableColumnResize, TableCaption,
    ...(profile === 'document' ? [Image, ImageCaption, ImageStyle, ImageToolbar, ImageResize, ImageUpload, LinkImage] : []), GalarisIntegration],
  menuBar: { isVisible: false },
  codeBlock: { languages: codeBlockLanguages(t) },
  fullscreen: { menuBar: { isVisible: false } },
  toolbar: { items: [...editorToolbarGroups(profile === 'document', Boolean(personalVoice)).map(group => 'galarisGroup' + group.name), 'galarisMobileToolbar'], shouldNotGroupWhenFull: true },
  style: { definitions: calloutKinds.map(kind => ({ name: t('richEditor.callouts.' + kind), element: 'blockquote', classes: ['galaris-callout', 'galaris-callout-' + kind] })) },
  heading: { options: [{ model: 'paragraph', title: 'Paragraph', class: 'ck-heading_paragraph' }, ...([1, 2, 3, 4, 5, 6] as const).map(level => ({ model: `heading${level}` as const, view: `h${level}`, title: `Heading ${level}`, class: `ck-heading_heading${level}` }))] },
  fontFamily: { options: ['default', 'Arial, Helvetica, sans-serif', 'Georgia, serif', 'Times New Roman, serif', 'Courier New, Courier, monospace'], supportAllValues: true },
  fontSize: { options: [10, 12, 14, 'default', 18, 24, 32, 48], supportAllValues: true },
  link: { toolbar: ['linkPreview', 'editLink', 'unlink', ...(profile === 'document' && createLinkCard ? ['|', 'documentLinkAppearance'] : [])], decorators: { newTab: { mode: 'automatic', callback: () => true, attributes: { target: '_blank', rel: 'noopener noreferrer' } } }, allowedProtocols: ['http', 'https', 'mailto', 'document', 'memory', 'galaris'], addTargetToExternalLinks: false },
  list: { properties: { styles: true, startIndex: true, reversed: true } },
  table: { contentToolbar: ['tableColumn', 'tableRow', 'mergeTableCells', 'tableProperties', 'tableCellProperties', 'toggleTableCaption'] },
  image: { toolbar: ['documentImagePreview', '|', 'imageTextAlternative', 'toggleImageCaption', '|', 'imageStyle:inline', 'imageStyle:wrapText', 'imageStyle:breakText', '|', 'resizeImage', 'linkImage', ...(createLinkCard ? ['documentLinkAppearance'] : [])], resizeUnit: '%' },
  htmlSupport: { allow: [{ name: /^(?:p|h[1-6]|span|mark|ol|li|td|th|code)$/, attributes: ['start', 'colwidth', 'data-color'], styles: ['text-align', 'background-color'], classes: [/^language-/] }, { name: 'blockquote', classes: ['galaris-link-card', 'galaris-media-audio', 'galaris-media-video', 'galaris-media-pdf'] }] },
}))
function navigate(uri: string): void {
  const attachment = attachmentReference(uri)
  if (attachment) { emit('open-attachment', ...attachment); return }
  const href = richLinkHref(uri)
  if (href) window.open(href, '_blank', 'noopener,noreferrer')
}
function openGalarisLinks(): void {
  const current = editor.value
  if (!current || readonly) return
  linkSelection = current.model.createSelection(current.model.document.selection)
  linkLabel.value = [...(linkSelection.getFirstRange()?.getItems() ?? [])].map(item => item.is('$textProxy') ? item.data : '').join('')
  linkOpen.value = true
}
function insertGalarisLink(uri: string, label: string): void {
  const current = editor.value
  if (!current || readonly || !linkSelection) return
  current.model.change(writer => {
    writer.setSelection(linkSelection!)
    current.execute('link', uri, {}, label === linkLabel.value && !linkSelection!.isCollapsed ? undefined : label)
  })
}
function ready(current: ClassicEditor): void {
  editor.value = current
  // Keep the native sticky panel active within the editor's bounds, even after blur.
  current.ui.view.stickyPanel.unbind('isActive')
  current.ui.view.stickyPanel.isActive = true
  const panel = current.ui.view.stickyPanel
  let resizeFrame = 0
  const panelObserver = new ResizeObserver(() => {
    if (resizeFrame) return
    resizeFrame = requestAnimationFrame(() => {
      resizeFrame = 0
      // CKEditor measures width and placeholder height only when entering sticky mode.
      panel.isSticky = false
      panel.checkIfShouldBeSticky()
    })
  })
  // A stacked pane can move the scroll viewport without resizing the toolbar itself.
  for (let ancestor = panel.element; ancestor; ancestor = ancestor.parentElement) panelObserver.observe(ancestor)
  panelObserver.observe(panel.contentPanelElement)
  current.on('destroy', () => {
    panelObserver.disconnect()
    cancelAnimationFrame(resizeFrame)
  })
  applyDocumentLayout(current)
  observeDocumentWidth(current)
  attachEditorToolbarGroups(current)
  // Keep native controls: headings and font size show their values, other controls use icons.
  for (const item of editorToolbarCommands(current)) {
    const button = item instanceof DropdownView ? item.buttonView : item instanceof ButtonView ? item : undefined
    if (!button) continue
    if (item.element?.classList.contains('ck-style-dropdown')) button.icon = IconBoxWithMarker
    if (item.element?.classList.contains('ck-font-size-dropdown') && button instanceof ButtonView) {
      button.set({ icon: undefined, withText: true, ariaLabel: button.label, ariaLabelledBy: undefined, tooltip: button.label })
      button.bind('label').to(current.commands.get('fontSize')!, 'value', (value: unknown) => value ? String(value) : current.t('Default'))
      continue
    }
    if (button.icon) button.withText = false
  }
  attachGnomeEditorIcons(current)
  lastEditorData = current.getData()
  current.model.document.on('change:data', () => changed(current.getData(), null, current))
  current.editing.view.change(writer => {
    const root = current.editing.view.document.getRoot()!
    writer.addClass('rich-content', root)
    writer.setAttribute('aria-label', ariaLabel || t('richEditor.content'), root)
  })
  // Keep CKEditor's native link preview while preserving the current document tab.
  const previews = new WeakSet<ButtonView>()
  const wireLinkPreview = () => {
    for (const item of current.plugins.get(LinkUI).toolbarView?.items ?? []) {
      if (!(item instanceof ButtonView) || !item.element?.classList.contains('ck-link-toolbar__preview')) continue
      if (!previews.has(item)) {
        previews.add(item)
        item.on<LinkPreviewButtonNavigateEvent>('navigate', (event, href, cancel) => {
          cancel(); event.stop(); navigate(href)
        }, { priority: 'high' })
      }
      item.tooltip = t('richEditor.open')
      item.element?.setAttribute('target', '_blank')
      item.element?.setAttribute('rel', 'noopener noreferrer')
      const href = 'href' in item && typeof item.href === 'string' && richLinkHref(item.href)
      if (href) item.element?.setAttribute('href', href)
    }
  }
  current.ui.on('update', wireLinkPreview)
  current.plugins.get(ContextualBalloon).on('change:visibleView', wireLinkPreview)
  // Resolve only navigation; the canonical link in the model is retained.
  const navigationOptions = { priority: 'highest', context: '$capture' } as const
  current.editing.view.document.on('click', (event, data) => {
    const target = data.domTarget instanceof Element ? data.domTarget.closest('a') : null
    if (!target || !((data.domEvent as MouseEvent).ctrlKey || (data.domEvent as MouseEvent).metaKey || readonly)) return
    data.preventDefault(); event.stop(); navigate(target.getAttribute('data-rich-reference') ?? target.getAttribute('href') ?? '')
  }, navigationOptions)
  current.editing.view.document.on('keydown', (event, data) => {
    if (!data.altKey || data.keyCode !== 13) return
    const uri = current.commands.get('link')?.value
    if (typeof uri !== 'string') return
    data.preventDefault(); event.stop(); navigate(uri)
  }, navigationOptions)
}
function insertResource(html: string): void {
  const current = editor.value
  if (!current || readonly) return
  current.model.change(writer => {
    if (resourceSelection) writer.setSelection(resourceSelection)
    const fragment = current.data.toModel(current.data.processor.toView(sanitizeRichHtml(html, profile)))
    current.model.insertContent(fragment)
  })
  resourceSelection = undefined
  current.editing.view.focus()
}
async function importHtml(html: string, current: Editor): Promise<void> {
  if (readonly) return
  const ranges = [...current.model.document.selection.getRanges()].map(range => ModelLiveRange.fromRange(range))
  importingHtml.value = true
  importRequest?.abort(); const request = new AbortController(); importRequest = request
  let imageFailed = false
  try {
    const imported = await pasteDocumentHtml(html, { signal: request.signal, upload: uploadImage, importImage,
      imageFailed: () => { imageFailed = true }, imageLabel: t('richEditor.resources.unavailableImage'),
    })
    if (request.signal.aborted || current !== editor.value || current.isReadOnly || ranges.some(range => range.root.rootName === '$graveyard')) return
    current.model.change(writer => {
      const fragment = current.data.toModel(current.data.processor.toView(imported))
      const selection = current.model.createSelection(ranges)
      current.model.insertContent(fragment, selection)
      writer.setSelection(selection)
    })
    if (imageFailed) $q.notify({ type: 'warning', message: t('richEditor.resources.pasteImagesFailed') })
    current.editing.view.focus()
  } catch { if (!request.signal.aborted) $q.notify({ type: 'negative', message: t('richEditor.resources.failed') }) }
  finally { ranges.forEach(range => range.detach()); if (importRequest === request) importingHtml.value = false }
}
async function prepareDocumentShare(): Promise<void> {
  const current = editor.value
  if (!current || !exportPdf) return
  shareRequest?.abort()
  const request = new AbortController()
  shareRequest = request
  shareOpen.value = true; sharePreparing.value = true; shareError.value = ''; shareFile.value = null
  try {
    const file = await createDocumentPdf(current.getData(), documentTitle || ariaLabel || t('richEditor.content'), request.signal, exportPdf, resolveImage, resolveRenderedContent.value)
    if (!request.signal.aborted && current === editor.value) shareFile.value = file
  } catch {
    if (!request.signal.aborted) shareError.value = t('richEditor.exportPdfFailed')
  } finally {
    if (shareRequest === request) sharePreparing.value = false
  }
}
function cancelDocumentShare(): void {
  shareRequest?.abort(); shareFile.value = null; shareError.value = ''; sharePreparing.value = false
}
async function shareDocument(): Promise<void> {
  if (!shareFile.value || sharing.value) return
  shareError.value = ''; sharing.value = true
  try {
    if (nativeShareData.value) await navigator.share(nativeShareData.value)
    else saveBlobAsResource(shareFile.value, shareFile.value.name)
    shareOpen.value = false
  } catch (error) {
    if (!(error instanceof DOMException && error.name === 'AbortError')) shareError.value = t('richEditor.share.failed')
  } finally { sharing.value = false }
}
function applyDocumentLayout(current: Editor): void {
  if (profile !== 'document') return
  current.editing.view.change(writer => {
    writer.setAttribute('data-document-layout', effectiveDocumentLayout.value, current.editing.view.document.getRoot()!)
  })
}
function observeDocumentWidth(current: Editor): void {
  if (profile !== 'document') return
  // The fixed page in ckeditorTheme.css is 210 mm, measured in CSS pixels.
  const fixedPageWidth = 210 * 96 / 25.4
  let container: HTMLElement | null = null
  let frame = 0
  const measure = () => {
    frame = 0
    const parent = current.ui.getEditableElement()?.parentElement ?? null
    if (parent !== container) {
      observer.disconnect()
      container = parent
      if (container) observer.observe(container)
    }
    if (!container || container.clientWidth === 0) return
    const style = getComputedStyle(container)
    const available = container.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
    documentFitsFixedWidth.value = available >= fixedPageWidth
  }
  const schedule = () => { if (!frame) frame = requestAnimationFrame(measure) }
  const observer = new ResizeObserver(schedule)
  const fullscreen = current.commands.get('toggleFullscreen')
  fullscreen?.on('change:value', schedule)
  measure()
  current.on('destroy', () => {
    observer.disconnect()
    cancelAnimationFrame(frame)
    fullscreen?.off('change:value', schedule)
  })
}
function changed(html: string, _event: unknown, current: Editor): void {
  if (applyingExternal || current !== editor.value) return
  if (html === lastEditorData) return
  lastEditorData = html
  const value = profile === 'document' ? restoreInteractiveHtml(sourceHtml(html)) : sourceHtml(html)
  if (value === (profile === 'document' ? restoreInteractiveHtml(sourceHtml(lastEmitted)) : sourceHtml(lastEmitted))) return
  lastEmitted = value
  emit('update:modelValue', value)
}
watch(() => modelValue, value => {
  if (value === lastEmitted) return
  personalVoice?.stop()
  shareOpen.value = false; cancelDocumentShare()
  printing?.abort()
  exportingPdf?.abort()
  exportingBundle?.abort()
  linkOpen.value = false
  importRequest?.abort(); resourceSelection = undefined
  linkSelection = undefined
  applyingExternal = true
  lastEmitted = value
  if (editor.value) {
    editor.value.setData(sourceHtml(value))
    lastEditorData = editor.value.getData()
  } else editorData.value = sourceHtml(value)
  applyingExternal = false
})
watch([() => profile, locale], () => {
  personalVoice?.stop()
  printing?.abort()
  exportingPdf?.abort()
  exportingBundle?.abort()
  linkOpen.value = false
  importRequest?.abort(); resourceSelection = undefined
  linkSelection = undefined
  editor.value = undefined
  editorData.value = sourceHtml(modelValue)
})
watch(() => readonly, value => { if (value) { linkOpen.value = false; importRequest?.abort() } })
watch(() => attachments, () => editor.value?.ui.update())
onBeforeUnmount(() => { printing?.abort(); exportingPdf?.abort(); exportingBundle?.abort(); importRequest?.abort(); cancelDocumentShare() })
/** Insert literal speech at the current model selection, retaining inline formatting. */
function insertDictation(text: string): void {
  const current = editor.value
  if (!current || current.isReadOnly || !text.trim()) return
  current.model.change(writer => {
    const selection = current.model.document.selection
    const position = selection.getFirstPosition()
    const before = position?.nodeBefore
    const after = selection.getLastPosition()?.nodeAfter
    const left = position?.textNode
      ? position.textNode.data.slice(0, position.offset - position.textNode.startOffset!).slice(-1)
      : before?.is('$text') ? before.data.slice(-1) : ''
    const end = selection.getLastPosition()
    const right = end?.textNode
      ? end.textNode.data.slice(end.offset - end.textNode.startOffset!, end.offset - end.textNode.startOffset! + 1)
      : after?.is('$text') ? after.data.slice(0, 1) : ''
    let spoken = text.trim()
    if (/[,.!?;:…]/.test(left)) spoken = spoken.replace(/^[,.!?;:…]+\s*/, '')
    if (!spoken) return
    const prefix = left && !/\s|[({[]/.test(left) && !/^[,.;:!?…)}\]]/.test(spoken) ? ' ' : ''
    const suffix = right && !/\s|[,.;:!?…)}\]]/.test(right) ? ' ' : ''
    const fragment = writer.createDocumentFragment()
    const lines = (prefix + spoken + suffix).split(/\r?\n/)
    for (const [index, line] of lines.entries()) {
      if (index) writer.append(writer.createElement('softBreak'), fragment)
      if (line) writer.append(writer.createText(line, selection.getAttributes()), fragment)
    }
    current.model.insertContent(fragment)
  })
  current.editing.view.focus()
}
defineExpose({ editor, insertResource, insertDictation })
</script>
