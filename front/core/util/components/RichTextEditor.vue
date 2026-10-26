<template>
  <div ref="root" class="rich-editor tiptap-galaris-editor" :class="{ 'editorial-fullscreen': fullscreen }" :style="{ '--editor-min-height': minHeight, '--editor-max-height': autoGrow ? 'none' : maxHeight }" @keydown="editorKeydown" @click.capture="editorClick" @contextmenu.capture="openContextMenu">
    <EditorialToolbar v-if="editor" :editor="editor" :revision="revision" :document="profile === 'document'" :source="sourceMode" :find-open="findOpen" :outline-open="outlineOpen" :single-row="singleRowToolbar" :hidden-groups="hiddenToolbarGroups" :full-width="effectiveLayout === 'full'" :fullscreen="fullscreen" :fits="fits" :disabled-actions="disabledActions" @action="action">
      <template v-if="personalVoice" #voice>
        <EditorialToolButton flat dense :color="voice?.dictating || voice?.dictationPending ? 'negative' : 'primary'" :icon="voice?.dictating || voice?.dictationPending ? 'stop' : 'mic'" :label="voice?.dictating ? voice.labels.finishDictation : voice?.dictationPending ? voice.labels.processing : voice?.labels.dictate ?? ''" :disable="readonly || sourceMode || voice?.reading" @click="voice?.toggleDictation()" />
        <EditorialToolButton flat dense color="primary" :icon="voice?.reading && !voice.paused ? 'pause' : 'play_arrow'" :label="voice?.reading ? voice.paused ? voice.labels.paused : voice.labels.reading : voice?.labels.read ?? ''" :disable="voice?.dictating || voice?.dictationPending" @click="action('read')" />
        <EditorialToolButton flat dense icon="expand_more" :label="voice?.labels.readingControls ?? ''">
          <q-menu><q-list dense role="menu" :aria-label="voice?.labels.readingControls">
            <q-item v-close-popup clickable role="menuitem" :aria-label="voice?.paused ? voice.labels.resume : voice?.labels.pause" :disable="!voice?.reading" @click="voice?.togglePause()">
              <q-item-section avatar><q-icon :name="voice?.paused ? 'play_arrow' : 'pause'" /></q-item-section><q-item-section>{{ voice?.paused ? voice.labels.resume : voice?.labels.pause }}</q-item-section>
            </q-item>
            <q-item v-close-popup clickable role="menuitem" :aria-label="voice?.labels.stop" :disable="!voice?.reading" @click="voice?.stop()">
              <q-item-section avatar><q-icon name="stop" /></q-item-section><q-item-section>{{ voice?.labels.stop }}</q-item-section>
            </q-item>
          </q-list></q-menu>
        </EditorialToolButton>
      </template>
      <template v-if="$slots['toolbar-actions']" #actions><slot name="toolbar-actions" :exit-fullscreen="exitFullscreen" /></template>
      <template v-if="mobileDocument && !readonly && !sourceMode" #context>
        <div class="editorial-mobile-context" role="toolbar" :aria-label="t('richEditor.contextActions')" @mousedown.prevent>
          <EditorialContextActions v-if="activeContext" toolbar :kind="activeContext.kind" :actions="contextActions" :readonly="readonly" :language="selectedAttributes.language ?? ''" :languages="languages" :table-classes="tableClasses" @action="runContextAction" @language="setCodeLanguage" @table-style="applyTableStyle" />
          <EditorialToolbar v-if="mobileTextContext" contextual :editor="editor" :revision="revision" document :hidden-groups="hiddenToolbarGroups" :disabled-actions="disabledActions" @action="action" />
        </div>
      </template>
    </EditorialToolbar>
    <div v-if="findOpen" class="editorial-search-bar" role="search" :aria-label="t('richEditor.find')">
      <q-input ref="searchInput" v-model="fields.search" class="editorial-search-input" dense outlined :label="t('richEditor.find')" @keydown.enter.prevent="findNext" />
      <q-input v-model="fields.replace" class="editorial-search-input" dense outlined :label="t('richEditor.replace')" :disable="readonly" @keydown.enter.prevent="replaceMatch" />
      <q-checkbox v-model="fields.matchCase" dense :label="t('richEditor.matchCase')" />
      <q-checkbox v-model="fields.wholeWords" dense :label="t('richEditor.wholeWords')" />
      <span role="status" aria-live="polite">{{ matches.length }}</span>
      <q-btn dense outline :label="t('richEditor.next')" :disable="!matches.length" @click="findNext" />
      <q-btn dense outline :label="t('richEditor.replaceAll')" :disable="readonly || !matches.length" @click="replaceAll" />
      <q-btn dense color="primary" :label="t('richEditor.replace')" :disable="readonly || !matches.length" @click="replaceMatch" />
      <q-btn flat round dense icon="close" :aria-label="t('common.close')" @click="closeFind" />
    </div>
    <div class="editorial-workspace">
      <DocumentOutline v-if="profile === 'document' && outlineOpen && editor" :editor="editor" :revision="revision" @close="outlineOpen = false" />
    <div class="editorial-body" :data-document-layout="profile === 'document' ? effectiveLayout : undefined">
      <EditorialSource v-if="sourceMode" :model-value="sourceDraft" :readonly="readonly" :label="t('richEditor.source')" @update:model-value="editSource" />
      <div v-show="!sourceMode" ref="editorHost" />
    </div>
    </div>
    <template v-if="!sourceMode">
      <Teleport v-for="target in codeCopies" :key="target.key" :to="target.element"><CodeBlockCopyButton :source="target.source" /></Teleport>
      <Teleport v-for="target in documentLinkIcons" :key="target.key" :to="target.element"><WorkingDocumentIcon :document-id="target.documentId" title="" size="1em" readonly /></Teleport>
      <Teleport v-for="target in embeddedTargets" :key="target.key" :to="target.element">
        <div class="editorial-embedded-rendering">
        <slot name="embedded-code" :source="target.source" :language="target.language" :register-snapshot="(capture: RenderedDocumentCapture | undefined) => registerSnapshot(target.key, capture)"><div class="q-pa-md">{{ t('richEditor.embeddedApplication') }}</div></slot>
        <q-btn v-if="readonly" flat class="editorial-object-preview" :aria-label="t('richEditor.interactivePreview')" @click.stop="objectPreview = target" />
        </div>
      </Teleport>
      <Teleport v-for="target in resourceEmbeds" :key="target.key" :to="target.element"><ResourceEmbed :uri="target.uri" :title="target.title" :agent-id="resourceAgentId" :register-snapshot="(capture: RenderedDocumentCapture | undefined) => registerResourceSnapshot(target.key, capture)" /></Teleport>
    </template>
      <q-menu v-if="activeContext || pointerTextContext" :id="pointerMenuId" ref="pointerMenu" v-model="pointerMenuOpen" :target="editorHost ?? false" no-parent-event touch-position no-refocus separate-close-popup :transition-duration="0" max-width="calc(100vw - 16px)" :max-height="pointerMenuMaxHeight" role="presentation" @escape-key="queueContextFocus" @hide="restoreContextFocus">
        <q-list dense role="menu" :aria-label="t(!activeContext ? 'richEditor.content' : activeContext.kind === 'code' ? 'richEditor.codeTools.toolbar' : activeContext.kind === 'table' ? 'richEditor.table' : activeContext.kind === 'object' ? 'richEditor.embeddedApplication' : activeContext.kind === 'equation' ? 'richEditor.equation.context' : 'richEditor.resources.insert')" @mousedown.prevent>
          <EditorialContextActions v-if="activeContext" :kind="activeContext.kind" :actions="contextActions" :readonly="readonly" :language="selectedAttributes.language ?? ''" :languages="languages" :table-classes="tableClasses" @action="runPointerAction" @language="setCodeLanguage" @table-style="applyTableStyle" />
          <template v-if="pointerTextContext && editor && !readonly">
            <q-separator v-if="activeContext" />
            <q-item v-for="key in clipboardActions" :key="key" clickable role="menuitem" :aria-label="t('richEditor.clipboard.' + key)" :disable="key !== 'paste' && editor.state.selection.empty" @click="clipboardAction(key)">
              <q-item-section avatar><q-icon :name="key === 'copy' ? 'content_copy' : key === 'cut' ? 'content_cut' : 'content_paste'" /></q-item-section>
              <q-item-section>{{ t('richEditor.clipboard.' + key) }}</q-item-section>
            </q-item>
            <q-separator />
            <EditorialToolbar menu :editor="editor" :revision="revision" :document="profile === 'document'" :find-open="findOpen" :outline-open="outlineOpen" :hidden-groups="hiddenToolbarGroups" :disabled-actions="disabledActions" @action="runPointerTextAction" />
          </template>
        </q-list>
      </q-menu>
    <ResourceDetailDialog v-if="resourceDetail" :target="resourceDetail" @close="resourceDetail = null" />
    <EquationDialog v-if="mathOpen" :kind="mathKind" :latex="mathLatex" @apply="applyMath" @close="closeMath" />
    <RenderedObjectPreview v-if="objectPreview" :key="objectPreview.key" :source="objectPreview.source" :language="objectPreview.language" :capture="capturePreview" :title="t('richEditor.interactivePreview')" @close="objectPreview = null" />
    <PdfPreview v-model="pdfPreview" />
    <FullscreenPreview v-model="imagePreviewOpen" :viewer-label="t('richEditor.resources.openImage')">
      <template #default="{ fit }"><img :src="imagePreview" :alt="t('richEditor.resources.openImage')" :style="{ maxWidth: fit ? '100vw' : 'none', maxHeight: fit ? '100dvh' : 'none' }" /></template>
    </FullscreenPreview>
    <audio v-if="personalVoice" ref="playbackElement" hidden />
    <div v-if="personalVoice?.error.value" role="alert" class="q-pa-sm">{{ personalVoice.error.value }}</div>
    <div v-if="uploadProgress" role="status" class="row items-center q-gutter-sm q-pa-sm"><q-linear-progress class="col" :value="uploadProgress.progress" /><span>{{ uploadProgress.name }} · {{ Math.round(uploadProgress.progress * 100) }}% · {{ uploadProgress.index }}/{{ uploadProgress.total }}</span><q-btn flat round dense icon="close" :aria-label="t('richEditor.resources.cancelUpload')" @click="uploadRequest?.abort()" /></div>
    <div v-if="importRequest" role="status" class="row items-center q-gutter-sm q-pa-sm"><q-spinner />{{ t('richEditor.resources.importingHtml') }}<q-btn flat round dense icon="close" :aria-label="t('common.cancel')" @click="importRequest?.abort()" /></div>
    <input v-if="profile === 'document'" ref="fileInput" type="file" multiple hidden @change="chooseFiles" />
    <InternalResourcePicker v-if="!pickResources && linkOpen" v-model:picker-open="linkOpen" :agent-id="resourceAgentId" :editable="!readonly" @picked="finishInternalSelection" />
    <q-dialog v-model="dialogOpen" :aria-label="t('richEditor.' + dialog)" @hide="releaseDialog">
      <q-card class="galaris-dialog-card" style="width: 480px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center"><div class="text-h6">{{ t('richEditor.' + dialog) }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section>
        <q-card-section class="galaris-dialog-body" :class="{ 'q-gutter-md': dialog !== 'help' }">
          <template v-if="dialog === 'link'"><q-input v-model="fields.url" :label="t('richEditor.uri')" /><q-input v-model="fields.text" :label="t('richEditor.linkText')" /></template>
          <template v-else-if="dialog === 'image'"><q-input v-model="fields.alt" :label="t('richEditor.alt')" /><q-input v-model="fields.caption" :label="t('richEditor.caption')" /><q-input v-model="fields.width" :label="t('richEditor.imageWidth')" /><q-select v-model="fields.imageStyle" :options="imageStyles" emit-value map-options :label="t('richEditor.imageStyle')" /><q-input v-model="fields.imageLink" :label="t('richEditor.link')" /></template>
          <template v-else-if="dialog === 'tableProperties' || dialog === 'cellProperties'"><q-input v-model="fields.width" :label="t('richEditor.width')" /><q-input v-model="fields.height" :label="t('richEditor.height')" /><q-input v-model="fields.background" :label="t('richEditor.backgroundColor')" /><q-input v-model="fields.border" :label="t('richEditor.border')" /><q-input v-if="dialog === 'tableProperties'" v-model="fields.caption" :label="t('richEditor.caption')" /></template>
          <template v-else-if="dialog === 'listProperties'"><q-input v-if="editor?.isActive('orderedList')" v-model="fields.start" type="number" min="1" :label="t('richEditor.listStart')" /><q-checkbox v-if="editor?.isActive('orderedList')" v-model="fields.reversed" :label="t('richEditor.reversed')" /><q-select v-model="fields.listStyle" :options="listStyles" emit-value map-options :label="t('richEditor.listStyle')" /></template>
          <template v-else-if="dialog === 'specialCharacters'"><div class="row q-gutter-xs"><q-btn v-for="character in '© ® ™ € £ ¥ α β γ Δ π Ω ± × ÷ ∞ ≈ ≠ ≤ ≥ ← → ↑ ↓ ✓ ✗ ☐ ☑'.split(' ')" :key="character" outline :label="character" @click="fields.text = character" /></div><q-input v-model="fields.text" :label="t('richEditor.specialCharacters')" /></template>
          <q-color v-else-if="dialog === 'fontColor' || dialog === 'backgroundColor'" v-model="fields.color" no-header no-footer />
          <q-markup-table v-else-if="dialog === 'help'" flat dense wrap-cells>
            <tbody><tr v-for="shortcut in keyboardShortcuts" :key="shortcut.label + shortcut.keys"><td>{{ shortcut.label }}</td><td class="text-right"><kbd>{{ shortcut.keys }}</kbd></td></tr></tbody>
          </q-markup-table>
        </q-card-section>
        <q-card-actions v-if="dialog !== 'help'" align="right"><q-btn v-close-popup outline :label="t('common.cancel')" /><q-btn color="primary" :label="t('richEditor.apply')" :disable="readonly" @click="applyDialog" /></q-card-actions>
      </q-card>
    </q-dialog>
    <q-dialog v-model="shareOpen" @hide="cancelShare">
      <q-card class="galaris-dialog-card" style="width: 420px; max-width: 95vw"><q-card-section class="galaris-dialog-title row items-center"><div class="text-h6">{{ t('richEditor.share.title') }}</div><q-space /><q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" /></q-card-section><q-card-section class="galaris-dialog-body"><div v-if="sharePreparing" role="status"><q-spinner />{{ t('richEditor.share.preparing') }}</div><div v-else-if="shareError" role="alert">{{ shareError }}</div><div v-else-if="shareFile">{{ shareFile.name }}</div></q-card-section><q-card-actions align="right"><q-btn v-close-popup outline :label="t('common.cancel')" /><q-btn v-if="shareError && !shareFile" outline :label="t('common.retry')" @click="prepareShare" /><q-btn v-else color="primary" :disable="!shareFile" :loading="sharing" :label="t(nativeShareData ? 'richEditor.share.action' : 'richEditor.share.save')" @click="shareDocument" /></q-card-actions></q-card>
    </q-dialog>
  </div>
</template>
<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, useSlots, useTemplateRef, watch } from 'vue'
import { useQuasar, copyToClipboard, type QInput, type QMenu } from 'quasar'
import { useI18n } from 'vue-i18n'
import { Editor } from '@tiptap/vue-3'
import { NodeSelection, TextSelection, type Selection } from '@tiptap/pm/state'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import { closeHistory } from '@tiptap/pm/history'
import { marked } from 'marked'
import EditorialToolButton from './EditorialToolButton.vue'
import EditorialToolbar from './EditorialToolbar.vue'
import type { MathKind } from '../mathRendering'
import DocumentOutline from './DocumentOutline.vue'
import EditorialSource from './EditorialSource.vue'
import EditorialContextActions from './EditorialContextActions.vue'
import { useContextMenuDismissal } from '../contextMenuDismissal'
import { withTableStyle, type TablePalette, type TableTreatment } from '../editorialTableStyles'
import { editorialIcon } from '../editorialIcons'
import { useDocumentLinkIcons } from '../documentLinkIcons'
import WorkingDocumentIcon from './WorkingDocumentIcon.vue'
import CodeBlockCopyButton from './CodeBlockCopyButton.vue'
import { reserveEditorialToolbarSpace } from '../editorialScrollPadding'
import { documentShortcut, editorialShortcuts, isAltGraphInput, readingShortcutCommands, shortcutKeys } from '../editorialShortcuts'
import RenderedObjectPreview from './RenderedObjectPreview.vue'
import FullscreenPreview from './FullscreenPreview.vue'
import { DocumentResourceReferences as InternalResourcePicker } from '../resourceContributions'
import PdfPreview from './PdfPreview.vue'
import { contentExtensions, resolveEditorLinks, type EditorObject, type EditorToolbarGroupName, type ObjectHost } from '../tiptapContent'
import { attachmentReference, canonicalRichLink, richLinkCard, richLinkHref, richLinkTarget, richLinkHasCard, richLinkTitle, sanitizeRichHtml, validRichLink, type ContentProfile } from '../richText'
import { documentUriFromLink } from '../documentResource'
import { mountWebLinkPreview } from '../webLinkPreview'
import { useReferenceFormatting } from '../resourceReference'
import { useDocumentNavigation } from '../documentNavigation'
import { alignImage, imageAlignment } from '../imageAlignment'
import { protectInteractiveHtml, restoreInteractiveHtml } from '../interactiveHtml'
import { ResourceDetailDialog, type ResourceDetailTarget } from '../resourceDetail'
import { ResourceEmbed, type ResourceEmbedTarget } from '../resourceEmbed'
import { prepareDocumentCard } from '../resourceCards'
import { documentPlayer, createDocumentPlayer, type PdfPreviewSource } from '../documentMedia'
import { documentResourceHtml, withAttachmentInventory, type DocumentResource } from '../documentResources'
import { pasteDocumentHtml } from '../pasteDocumentHtml'
import { pastedMarkdownHtml } from '../pasteMarkdown'
import { editorVoiceProvider } from '../editorVoice'
import { printDocument } from '../printDocument'
import { createDocumentPdf, exportDocumentPdf } from '../exportDocumentPdf'
import { exportDocumentBundle } from '../exportDocumentBundle'
import { saveBlobAsResource } from '../resourceViewer'
import type { RenderedDocumentCapture, RenderedDocumentResolver } from '../renderedDocument'
import '../editorialTheme.css'
const EquationDialog = defineAsyncComponent(() => import('./EquationDialog.vue'))
const { modelValue, mediaType = 'text/html', profile = 'rich-text', readonly = false, minHeight = '240px', maxHeight = '70vh', autoGrow = false, ariaLabel = '', documentTitle = '', documentUrl = '', exportPdf, exportBundle, uploadImage, uploadFile, importImage, resolveImage, attachments = [], createLinkCard, hiddenToolbarGroups = [], singleRowToolbar = false, resourceAgentId = null, pickResources } = defineProps<{
  resourceAgentId?: number | null; modelValue: string; mediaType?: string; profile?: ContentProfile; readonly?: boolean; minHeight?: string; maxHeight?: string; autoGrow?: boolean; ariaLabel?: string; attachments?: DocumentResource[]; hiddenToolbarGroups?: readonly EditorToolbarGroupName[]; singleRowToolbar?: boolean
  createLinkCard?: (url: string) => Promise<string>; pickResources?: () => Promise<string>; exportBundle?: (html: string, signal: AbortSignal) => Promise<Blob>; documentTitle?: string; documentUrl?: string
  uploadFile?: (file: File, signal: AbortSignal, progress: (value: number) => void) => Promise<string>; exportPdf?: (html: string, signal: AbortSignal) => Promise<Blob>
  uploadImage?: (file: File, signal: AbortSignal, progress: (value: number) => void) => Promise<string>; importImage?: (url: string, signal: AbortSignal) => Promise<string>; resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; 'open-attachment': [documentId: string, attachmentId: string] }>()
const { t, locale } = useI18n(), $q = useQuasar(), slots = useSlots()
const referenceFormatting = useReferenceFormatting()
const navigateDocument = useDocumentNavigation()
const keyboardShortcuts = computed(() => [
  ...editorialShortcuts.filter(([, , command]) => !readonly || readingShortcutCommands.has(command)).map(([key, binding, , value]) => ({ label: t('richEditor.' + key, { level: Number(value) }), keys: shortcutKeys(binding, Boolean($q.platform.is.safari)) })),
  ...([
    ...(!readonly ? [
    ['shortcuts.tableNavigation', 'Tab / Shift+Tab'], ['shortcuts.listNesting', 'Tab / Shift+Tab'], ['shortcuts.codeIndentation', 'Tab / Shift+Tab'],
    ['shortcuts.headingNesting', 'Tab / Shift+Tab'], ['shortcuts.insertBeside', 'Alt+Enter'],
    ['shortcuts.lineBreak', 'Shift+Enter'],
    ] as const : []),
    ['shortcuts.documentStart', $q.platform.is.mac ? 'Cmd+ArrowUp' : 'Ctrl+Home'], ['shortcuts.documentEnd', $q.platform.is.mac ? 'Cmd+ArrowDown' : 'Ctrl+End'],
    ['shortcuts.selectDocumentStart', $q.platform.is.mac ? 'Cmd+Shift+ArrowUp' : 'Ctrl+Shift+Home'], ['shortcuts.selectDocumentEnd', $q.platform.is.mac ? 'Cmd+Shift+ArrowDown' : 'Ctrl+Shift+End'],
    ['shortcuts.openLink', 'Alt+Enter'], ['shortcuts.toolbarFocus', 'Alt+F10'], ['help', 'Alt+0'],
  ] as const).map(([key, keys]) => ({ label: t('richEditor.' + key), keys })),
])
const root = useTemplateRef('root'), fileInput = useTemplateRef('fileInput'), playbackElement = useTemplateRef('playbackElement')
const editorHost = useTemplateRef('editorHost'), selectedCardImage = ref('')
const imagePreview = ref('')
const imagePreviewOpen = computed({ get: () => Boolean(imagePreview.value), set: (open: boolean) => { if (!open) imagePreview.value = '' } })
const editor = shallowRef<Editor>(), revision = ref(0), sourceMode = ref(false), sourceDraft = ref(''), fullscreen = ref(false), layout = ref<'fixed' | 'full'>('fixed'), fits = ref(true)
const findOpen = ref(false), searchInput = useTemplateRef<QInput>('searchInput')
const outlineOpen = ref(false)
function exitFullscreen(): void { fullscreen.value = false }
const codeCopies = shallowRef<Array<{ key: number; element: HTMLElement; source: () => string }>>([])
const pointerMenu = useTemplateRef<QMenu>('pointerMenu')
const pointerMenuOpen = ref(false)
const pointerMenuY = ref(0)
// Quasar's point-positioned menus flip without capping the opposite side.
// Bound tall editor menus to the roomier side so every action stays reachable.
const pointerMenuMaxHeight = computed(() => `min(80vh, ${Math.max(pointerMenuY.value, $q.screen.height - pointerMenuY.value) - 8}px)`)
const pointerMenuId = useContextMenuDismissal(pointerMenuOpen, () => pointerMenu.value)
const pointerTextContext = ref(false)
let pointerSelection: Selection | undefined, pointerRequest = 0
let restoreContextOnHide = false
const effectiveLayout = computed(() => fits.value ? layout.value : 'full')
const embeddedTargets = shallowRef<EditorObject[]>([]), resourceEmbeds = shallowRef<ResourceEmbedTarget[]>([]), resourceDetail = shallowRef<ResourceDetailTarget | null>(null), pdfPreview = shallowRef<PdfPreviewSource | null>(null)
const { targets: documentLinkIcons, mount: mountDocumentLinkIcon, decorate: decorateDocumentLink } = useDocumentLinkIcons()
const objectPreview = shallowRef<EditorObject | null>(null)
const captures = new Map<number, RenderedDocumentCapture>(), requests = new Set<AbortController>(), urls = new Set<string>()
const resourceCaptures = new Map<number, RenderedDocumentCapture>()
const imageCache = new Map<string, Promise<Blob>>()
const exportJobs = new Map<string, AbortController>(), exportBusy = ref<string[]>([])
const disabledActions = computed(() => [...exportBusy.value, ...(!exportPdf ? ['exportPdf', 'share.action'] : []), ...(!exportBundle ? ['resources.documentExportBundle'] : [])])
let generation = 0, lastEmitted = modelValue, applyingExternal = false
let altGraphPressed = false
function trackKeyboardModifiers(event: KeyboardEvent): void {
  if (event.key === 'AltGraph' || event.code === 'AltRight' && event.getModifierState('AltGraph') && !event.metaKey && !$q.platform.is.mac) altGraphPressed = event.type === 'keydown'
  if (event.type === 'keyup' && event.code === 'AltRight') altGraphPressed = false
}
function resetKeyboardModifiers(): void { altGraphPressed = false }
interface Anchor { from: number; to: number; valid: boolean; generation: number }
const anchors = new Set<Anchor>()
function anchor(from = editor.value?.state.selection.from ?? 1, to = editor.value?.state.selection.to ?? from): Anchor { const value = { from, to, valid: true, generation }; anchors.add(value); return value }
function valid(value: Anchor): boolean { return value.valid && value.generation === generation && Boolean(editor.value?.isEditable) && !sourceMode.value }
function release(value?: Anchor): void { if (value) { value.valid = false; anchors.delete(value) } }
const mathOpen = ref(false), mathKind = ref<MathKind>('inline'), mathLatex = ref('')
let mathAnchor: Anchor | undefined, mathOriginal: ProseMirrorNode | undefined
function closeMath(restoreFocus = true): void {
  const opened = mathOpen.value, current = editor.value, started = generation
  mathOpen.value = false; release(mathAnchor); mathAnchor = undefined; mathOriginal = undefined
  if (opened && restoreFocus) void nextTick(() => {
    if (current && editor.value === current && !current.isDestroyed && generation === started && current.isEditable && !mathOpen.value) current.view.focus()
  })
}
function openMath(kind: MathKind, position?: number): void {
  const current = editor.value
  if (!current || readonly || sourceMode.value) return
  closeMath(false)
  const selection = current.state.selection
  const node = position !== undefined ? current.state.doc.nodeAt(position) : selection instanceof NodeSelection ? selection.node : undefined
  const existing = node && ['inlineMath', 'blockMath'].includes(node.type.name) ? node : undefined
  mathKind.value = position !== undefined && existing ? existing.type.name === 'inlineMath' ? 'inline' : 'block' : kind
  mathLatex.value = existing ? String(existing.attrs.latex) : ''
  mathAnchor = existing ? anchor(position ?? selection.from, (position ?? selection.from) + existing.nodeSize) : anchor()
  mathOriginal = existing
  mathOpen.value = true
}
function applyMath(latex: string): void {
  const at = mathAnchor, current = editor.value
  if (!current || !at || !valid(at) || !latex.trim() || latex.length > 10_000) return
  if (mathOriginal && !current.state.doc.nodeAt(at.from)?.eq(mathOriginal)) { closeMath(); return }
  const node = document.createElement(mathKind.value === 'inline' ? 'span' : 'p')
  node.dataset.math = mathKind.value; node.textContent = latex
  insertAt(at, node.outerHTML)
  closeMath()
}
function request(): AbortController { const value = new AbortController(); requests.add(value); return value }
function stop(): void { closeMath(false); pointerRequest++; pointerMenu.value?.hide(); pointerTextContext.value = false; pointerSelection = undefined; generation++; requests.forEach(value => value.abort()); requests.clear(); exportJobs.clear(); exportBusy.value = []; anchors.forEach(value => { value.valid = false }); anchors.clear(); personalVoice?.stop(); uploadProgress.value = null; importRequest.value = null; shareOpen.value = false; dialogOpen.value = false; findOpen.value = false; linkOpen.value = false; objectPreview.value = null }
function inputHtml(value: string): string {
  if (mediaType === 'text/markdown') value = marked.parse(value, { async: false })
  if (mediaType === 'text/plain') { const paragraph = document.createElement('p'); paragraph.textContent = value; value = paragraph.outerHTML }
  return sanitizeRichHtml(profile === 'document' ? protectInteractiveHtml(value) : value, profile)
}
function editableHtml(value: string): string { return sanitizeRichHtml(profile === 'document' ? protectInteractiveHtml(value) : value, profile) }
function html(): string { return profile === 'document' ? restoreInteractiveHtml(sanitizeRichHtml(editor.value?.getHTML() ?? inputHtml(modelValue), profile)) : sanitizeRichHtml(editor.value?.getHTML() ?? inputHtml(modelValue), profile) }
function publish(value: string): void { if (applyingExternal || value === lastEmitted) return; lastEmitted = value; emit('update:modelValue', value) }
function registerSnapshot(key: number, capture?: RenderedDocumentCapture): void { if (capture) captures.set(key, capture); else captures.delete(key) }
function registerResourceSnapshot(key: number, capture?: RenderedDocumentCapture): void { if (capture) resourceCaptures.set(key, capture); else resourceCaptures.delete(key) }
const capturePreview: RenderedDocumentCapture = signal => {
  const capture = objectPreview.value && captures.get(objectPreview.value.key)
  if (!capture) return Promise.reject(new Error('Current rendering unavailable'))
  return capture(signal)
}
const rendered: RenderedDocumentResolver = async (source, language, index, signal) => {
  if (language === 'galaris-resource-card') {
    const target = [...resourceEmbeds.value].sort((a, b) => a.element.compareDocumentPosition(b.element) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1)[index]
    const capture = target && resourceCaptures.get(target.key)
    if (!target || target.uri !== source || !capture) throw new Error('Resource rendering unavailable')
    return capture(signal)
  }
  const target = [...embeddedTargets.value].sort((a, b) => a.element.compareDocumentPosition(b.element) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1)[index]
  const capture = target && captures.get(target.key)
  if (!target || target.source !== source || target.language !== language || !capture) throw new Error('Current rendering unavailable')
  return capture(signal)
}
const renderedResolver = computed(() => slots['embedded-code'] || resourceEmbeds.value.length ? rendered : undefined)
function resolveAttachment(uri: string, image: HTMLImageElement): () => void {
  let disposed = false, url: string | undefined
  const reference = attachmentReference(uri)
  if (reference && resolveImage) {
    let pending = imageCache.get(uri)
    if (!pending) { pending = Promise.resolve().then(() => resolveImage!(...reference)); imageCache.set(uri, pending) }
    const active = pending
    void active.then(blob => {
    if (disposed) return
    url = URL.createObjectURL(blob); urls.add(url); image.src = url
    }).catch(() => { if (imageCache.get(uri) === active) imageCache.delete(uri) })
  }
  return () => { disposed = true; if (url) { URL.revokeObjectURL(url); urls.delete(url) } }
}
let hostKey = 0
function mountCodeCopy(element: HTMLElement, source: () => string): () => void {
  const target = { key: ++hostKey, element, source }
  let disposed = false
  queueMicrotask(() => { if (!disposed && element.isConnected) codeCopies.value = [...codeCopies.value, target] })
  return () => { disposed = true; codeCopies.value = codeCopies.value.filter(value => value.key !== target.key) }
}
function mountCard(target: ObjectHost): () => void {
  const disposals: Array<() => void> = []
  const links = [...target.element.querySelectorAll('a')]
  links.forEach(link => disposals.push(decorateDocumentLink(link)))
  const link = links[0], uri = link?.getAttribute('href') ?? ''
  for (const image of target.element.querySelectorAll('img')) { const src = image.getAttribute('src') ?? ''; image.dataset.editorAttachment = src; image.removeAttribute('src'); disposals.push(resolveAttachment(src, image)) }
  if (profile === 'document') disposals.push(mountWebLinkPreview(target.element, resourceAgentId))
  if ((target.element.matches('.galaris-process-diagram, .galaris-agent-card') || ['document', 'document_folder'].includes(richLinkTarget(uri)?.kind ?? '')) && richLinkTarget(uri)) {
    prepareDocumentCard(target.element)
    const element = document.createElement('div'); element.className = 'galaris-resource-embed'; target.element.append(element)
    const embed = { key: ++hostKey, element, uri, title: link?.textContent ?? '' }
    queueMicrotask(() => { if (element.isConnected) resourceEmbeds.value = [...resourceEmbeds.value, embed] })
    disposals.push(() => { resourceEmbeds.value = resourceEmbeds.value.filter(value => value.key !== embed.key) })
  } else {
    const resource = attachments.find(value => value.uri === uri)
    const player = documentPlayer(uri, resource?.name ?? link?.textContent ?? '', [...target.element.classList], resource?.mediaType)
    if (player) { const media = createDocumentPlayer(document, player, (doc, id) => resolveImage?.(doc, id), t, value => { pdfPreview.value = value });  media.element.dataset.documentPlayer = ''; target.element.append(media.element); disposals.push(media.dispose) }
  }
  return () => disposals.forEach(dispose => dispose())
}
function createEditor(): void {
  imagePreview.value = ''
  editor.value?.destroy(); embeddedTargets.value = []; resourceEmbeds.value = []; captures.clear(); resourceCaptures.clear(); selectedCardImage.value = ''
  editor.value = new Editor({
    element: editorHost.value!,
    content: inputHtml(modelValue), editable: !readonly, enableInputRules: profile === 'document',
    extensions: contentExtensions({ profile, object: (target, mounted) => { embeddedTargets.value = mounted ? [...embeddedTargets.value, target] : embeddedTargets.value.filter(value => value.key !== target.key); if (!mounted) captures.delete(target.key) },
      card: mountCard, image: resolveAttachment, openImage: navigate, readonly: () => readonly, codeCopy: mountCodeCopy, linkIcon: mountDocumentLinkIcon, editMath: position => openMath('inline', position) }),
    editorProps: { attributes: { class: 'rich-content', 'aria-label': ariaLabel || t('richEditor.content'), 'data-editor-surface': '', tabindex: '0' },
      decorations: state => {
        if (!findOpen.value) return null
        return DecorationSet.create(state.doc, findMatches(state.doc).map(({ from, to }) => Decoration.inline(from, to, {
          nodeName: 'mark', class: 'editorial-search-match', 'data-search-match': '',
          ...(state.selection.from === from && state.selection.to === to ? { 'data-search-current': '' } : {}),
        })))
      },
      handleDOMEvents: { keydown: (view, event) => {
        if (!readonly) return false
        const handled = editor.value?.options.editorProps?.handleKeyDown?.call(view, view, event)
        if (handled) event.preventDefault()
        return Boolean(handled)
      } },
      handlePaste: (view, event) => handleTransfer(event.clipboardData, view.state.selection.from, event),
      handleDrop: (view, event, _slice, moved) => moved ? false : handleTransfer(event.dataTransfer, view.posAtCoords({ left: event.clientX, top: event.clientY })?.pos ?? view.state.selection.from, event),
      handleClickOn: (view, _pos, node, nodePos, _event, direct) => {
        if (!direct || !['documentImage', 'inlineImage', 'resourceCard'].includes(node.type.name)) return false
        if (readonly && node.type.name !== 'resourceCard') return true
        view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc, nodePos)))
        view.focus()
        return true
      },
      handleKeyDown: (_view, event) => {
        if (event.isComposing || editor.value?.view.composing || isAltGraphInput(event, altGraphPressed)) return false
        syncKeyboardSelection()
        const current = editor.value; if (!current) return false
        const mod = event.ctrlKey || event.metaKey
        if ((!readonly || profile === 'document') && !event.altKey && (mod && ['Home', 'End'].includes(event.key) || event.metaKey && ['ArrowUp', 'ArrowDown'].includes(event.key))) {
          const end = ['End', 'ArrowDown'].includes(event.key), { selection, doc } = current.state
          const target = (end ? TextSelection.atEnd(doc) : TextSelection.atStart(doc)).head
          current.commands.setTextSelection(event.shiftKey ? { from: selection.anchor, to: target } : target)
          return true
        }
        if (event.altKey && !mod && !event.shiftKey && event.code === 'Digit0' && profile === 'document') { showDialog('help'); return true }
        if (event.altKey && !mod && !event.shiftKey && event.key === 'Enter') {
          if (!readonly && profile === 'document' && insertAtObjectEdge()) return true
          const link = window.getSelection()?.anchorNode?.parentElement?.closest('a'); const uri = link?.dataset.richReference ?? link?.getAttribute('href') ?? selectionUri(); if (uri) { navigate(uri); return true }
        }
        if (event.altKey && !mod && !event.shiftKey && event.key === 'F10') { root.value?.querySelector<HTMLElement>('[role="toolbar"] button')?.focus(); return true }
        if (!mod && !event.altKey && (event.key === 'ContextMenu' || event.shiftKey && event.key === 'F10')) { event.preventDefault(); void openKeyboardContextMenu(); return true }
        const shortcut = profile === 'document' ? documentShortcut(event, altGraphPressed) : undefined
        if (shortcut?.[2] === 'find') { event.preventDefault(); showDialog('find'); return true }
        if (shortcut && readingShortcutCommands.has(shortcut[2])) { event.preventDefault(); action(shortcut[2], shortcut[3]); return true }
        if (mod && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'f') { showDialog('find'); return true }
        if (readonly) return false
        if (mod && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'k') { showDialog('link'); return true }
        if (profile !== 'document') return false
        if (event.key === 'Tab' && !mod && !event.altKey && current.isActive('table')) {
          event.preventDefault()
          const moved = event.shiftKey ? current.commands.goToPreviousCell() : current.commands.goToNextCell()
          if (!moved && !event.shiftKey) current.chain().addRowAfter().goToNextCell().run()
          return true
        }
        if (event.key === 'Tab' && !mod && !event.altKey && current.isActive('listItem') && !current.isActive('codeBlock')) { indent(event.shiftKey ? -1 : 1); return true }
        if (event.key === 'Tab' && !mod && !event.altKey && current.isActive('heading') && current.state.selection.empty && current.state.selection.$from.parentOffset === 0) {
          const level = Math.min(6, Math.max(1, Number(current.getAttributes('heading').level) + (event.shiftKey ? -1 : 1)))
          current.commands.setHeading({ level: level as 1 | 2 | 3 | 4 | 5 | 6 }); return true
        }
        if (shortcut) { event.preventDefault(); const [, , command, value] = shortcut; action(command, value); return true }
        return false
      },
      handleClick: (_view, pos, event) => { const link = event.target instanceof Element ? event.target.closest('a') : null; if (readonly && event.target instanceof Element && event.target.closest('pre')) editor.value?.commands.setTextSelection(pos); if (!link || !(event.ctrlKey || event.metaKey || readonly)) return false; event.preventDefault(); navigate(link.dataset.richReference ?? link.getAttribute('href') ?? ''); return true },
    },
    onTransaction: ({ transaction, editor: current }) => {
      // Native focus restoration may move the caret inside the same code block;
      // its commands still apply to that whole block. Table cells keep exact selections.
      const sameCode = pointerSelection && transaction.selection.$from.parent.type.name === 'codeBlock' && transaction.selection.$from.sameParent(pointerSelection.$from)
      if (transaction.docChanged || transaction.selectionSet && pointerSelection && !transaction.selection.eq(pointerSelection) && !sameCode) pointerMenu.value?.hide()
      for (const value of anchors) { const from = transaction.mapping.mapResult(value.from, 1), to = transaction.mapping.mapResult(value.to, -1); value.from = from.pos; value.to = Math.max(from.pos, to.pos); if (from.deletedAcross && to.deletedAcross) value.valid = false }
      revision.value++; nextTick(() => { if (!current.isDestroyed) resolveEditorLinks(current) })
    },
    onUpdate: () => { if (!sourceMode.value) publish(html()) },
  })
  nextTick(() => { if (editor.value) resolveEditorLinks(editor.value) })
}
const personalVoice = editorVoiceProvider?.({ html, editable: () => !readonly && !sourceMode.value, playbackElement: () => playbackElement.value ?? undefined, insert: insertDictation })
const voice = computed(() => personalVoice?.controls.value)
const selectedType = computed(() => { void revision.value; const current = editor.value; if (!current) return ''; const selection = current.state.selection; return selection instanceof NodeSelection ? selection.node.type.name : current.isActive('codeBlock') ? 'codeBlock' : '' })
const selectedAttributes = computed(() => { void revision.value; return editor.value?.getAttributes(selectedType.value) ?? {} })
const activeContext = computed(() => {
  void revision.value
  const current = editor.value
  if (readonly || !current || current.isDestroyed || sourceMode.value) return null
  let kind: 'code' | 'table' | 'resource' | 'object' | 'equation'
  if (selectedType.value === 'codeBlock') kind = 'code'
  else if (['inlineMath', 'blockMath'].includes(selectedType.value)) kind = 'equation'
  else if (['documentImage', 'inlineImage', 'resourceCard'].includes(selectedType.value) || current.isActive('link')) kind = 'resource'
  else if (selectedType.value === 'rawObject') kind = 'object'
  else if (current.isActive('table')) kind = 'table'
  else return null
  return { kind }
})
const mobileDocument = computed(() => profile === 'document' && $q.screen.lt.md)
const mobileTextContext = computed(() => { void revision.value; return editor.value && !(editor.value.state.selection instanceof NodeSelection) && !editor.value.isActive('codeBlock') })
watch(mobileDocument, () => pointerMenu.value?.hide())
const canInsertBeside = computed(() => {
  void revision.value
  const selection = editor.value?.state.selection
  return Boolean(selection instanceof NodeSelection && (selection.node.isBlock || selection.node.type.name === 'inlineMath')) || ['code', 'table'].includes(activeContext.value?.kind ?? '')
})
const canConvertCard = computed(() => { void revision.value; const uri = selectionUri(); return profile === 'document' && (richLinkHasCard(uri) || Boolean(createLinkCard) && /^https?:\/\//i.test(uri)) })
const selectedDocumentUri = computed(() => { void revision.value; return documentUriFromLink(selectionUri(), window.location.origin) })
const languageNames: Record<string, string> = { javascript: 'JavaScript', typescript: 'TypeScript', graphql: 'GraphQL', cpp: 'C++', cs: 'C#', html: 'HTML', css: 'CSS', scss: 'SCSS', xml: 'XML', yaml: 'YAML', json: 'JSON', sql: 'SQL', php: 'PHP', ini: 'INI' }
const languages = computed(() => ['plaintext', 'text', 'bash', 'c', 'cs', 'cpp', 'css', 'diff', 'go', 'graphql', 'html', 'ini', 'java', 'javascript', 'json', 'kotlin', 'lua', 'makefile', 'markdown', 'perl', 'php', 'python', 'r', 'ruby', 'rust', 'scss', 'sql', 'swift', 'typescript', 'xml', 'yaml'].map(value => ({ value, label: value === 'plaintext' ? t('richEditor.codeTools.automatic') : value === 'text' ? t('richEditor.codeTools.plainText') : languageNames[value] ?? value[0]!.toUpperCase() + value.slice(1) })))
function insertAt(value: Anchor, markup: string, focus = true): void {
  if (!valid(value)) return
  const current = editor.value!, bookmark = current.state.selection.getBookmark()
  current.view.dispatch(closeHistory(current.state.tr))
  let end = value.from
  current.chain().insertContentAt({ from: value.from, to: value.to }, editableHtml(markup), { updateSelection: true }).command(({ tr }) => {
    end = tr.selection.to
    if (!focus) tr.setSelection(bookmark.map(tr.mapping).resolve(tr.doc))
    return true
  }).run()
  value.from = value.to = end
  if (focus) current.view.focus()
}
function insertResource(markup: string): void { if (readonly) return; const value = anchor(); insertAt(value, markup); release(value) }
function insertDictation(text: string): void { if (readonly || sourceMode.value || !text.trim()) return; const current = editor.value; if (!current) return; const { $from, $to } = current.state.selection; const before = $from.parent.textBetween(Math.max(0, $from.parentOffset - 1), $from.parentOffset), after = $to.parent.textBetween($to.parentOffset, Math.min($to.parent.content.size, $to.parentOffset + 1)); const value = (before && !/\s/.test(before) ? ' ' : '') + text.trim() + (after && !/\s|[,.;:!?]/.test(after) ? ' ' : ''); current.chain().focus().insertContent(value.split(/\r?\n/).flatMap((line, i) => [...(i ? [{ type: 'hardBreak' }] : []), ...(line ? [{ type: 'text', text: line }] : [])])).run() }
const uploadProgress = shallowRef<{ name: string; index: number; total: number; progress: number } | null>(null)
let uploadRequest: AbortController | undefined
const importRequest = shallowRef<AbortController | null>(null)
async function upload(files: File[], position: number): Promise<void> {
  const handler = uploadFile ?? uploadImage
  if (readonly || !handler || !files.length) return
  uploadRequest?.abort(); const pending = request(); uploadRequest = pending; const at = anchor(position)
  try { for (const [index, file] of files.entries()) {
    if (pending.signal.aborted || !valid(at)) break
    uploadProgress.value = { name: file.name, index: index + 1, total: files.length, progress: 0 }
    try { const uri = await handler(file, pending.signal, progress => { if (!pending.signal.aborted && valid(at)) uploadProgress.value = { name: file.name, index: index + 1, total: files.length, progress } }); if (!pending.signal.aborted && valid(at)) insertAt(at, documentResourceHtml({ uri, name: file.name, size: file.size, mediaType: file.type }), false) }
    catch { if (!pending.signal.aborted) $q.notify({ type: 'negative', message: t('richEditor.resources.uploadFailed', { name: file.name }) }) }
  } } finally { release(at); requests.delete(pending); if (uploadRequest === pending) uploadProgress.value = null }
}
function chooseFiles(event: Event): void { const input = event.target as HTMLInputElement; void upload(Array.from(input.files ?? []), editor.value?.state.selection.from ?? 1); input.value = '' }
function handleTransfer(data: DataTransfer | null, position: number, event: Event): boolean {
  if (!data || readonly || sourceMode.value) return false
  if (data.files.length && profile === 'document') { event.preventDefault(); void upload(Array.from(data.files), position); return true }
  if (editor.value?.isActive('codeBlock') || editor.value?.isActive('code')) return false
  const plain = data.getData('text/plain') || data.getData('text/uri-list') || data.getData('text/markdown')
  const markup = data.getData('text/html') || (profile === 'document' && /^(?:<!doctype\s+html\b|<(?:html|head|body|p|h[1-6]|div|section|article|main|table|ul|ol|blockquote|pre|img|figure|style)\b)/i.test(plain.trim()) ? plain : '')
  const documentUri = documentUriFromLink(plain.trim(), window.location.origin)
    ?? canonicalRichLink(plain.trim())
  if (documentUri) {
    event.preventDefault()
    if (event instanceof DragEvent && data.effectAllowed === 'copyMove') data.dropEffect = 'copy'
    const at = anchor(position, event instanceof ClipboardEvent ? editor.value?.state.selection.to ?? position : position)
    const link = new DOMParser().parseFromString(markup, 'text/html').querySelector('a')
    const copiedUri = link?.getAttribute('href') ?? ''
    const label = link && (documentUriFromLink(copiedUri, window.location.origin) ?? canonicalRichLink(copiedUri)) === documentUri ? link.textContent?.trim() : undefined
    const title = label && label !== plain.trim() && label !== documentUri ? label : undefined
    void insertDocumentLink(documentUri, at, title)
    return true
  }
  if (/^https?:\/\/\S+$/i.test(plain.trim()) && validRichLink(plain.trim())) { event.preventDefault(); const link = document.createElement('a'); link.href = plain.trim(); link.textContent = plain.trim(); insertResource(link.outerHTML); return true }
  const markdown = pastedMarkdownHtml(plain, markup)
  if (markdown !== null || markup) { event.preventDefault(); const at = anchor(position); if (profile === 'document') void importHtml(markdown ?? markup, at); else { insertAt(at, markdown ?? markup); release(at) }; return true }
  return false
}
async function insertDocumentLink(uri: string, at: Anchor, title?: string | null): Promise<void> {
  const pending = request()
  let label = title
  try {
    label ||= await richLinkTitle(uri, resourceAgentId, referenceFormatting())
  } catch {
    if (!pending.signal.aborted && valid(at)) $q.notify({ type: 'warning', message: t('richEditor.resources.failed') })
  } finally {
    if (!pending.signal.aborted && valid(at)) {
      const link = document.createElement('a'); link.href = uri; link.textContent = label || uri
      insertAt(at, link.outerHTML, Boolean(title))
    }
    release(at); requests.delete(pending)
  }
}
async function importHtml(markup: string, at: Anchor): Promise<void> {
  importRequest.value?.abort(); const pending = request(); importRequest.value = pending; let failed = false
  try { const value = await pasteDocumentHtml(markup, { signal: pending.signal, upload: uploadImage, importImage, imageFailed: () => { failed = true }, imageLabel: t('richEditor.resources.unavailableImage') }); if (!pending.signal.aborted) { insertAt(at, value, false); if (failed) $q.notify({ type: 'warning', message: t('richEditor.resources.pasteImagesFailed') }) } }
  catch { if (!pending.signal.aborted) $q.notify({ type: 'negative', message: t('richEditor.resources.failed') }) }
  finally { release(at); requests.delete(pending); if (importRequest.value === pending) importRequest.value = null }
}
const linkOpen = ref(false); let linkAnchor: Anchor | undefined
function insertInternalResources(value: string, at: Anchor): void {
  try {
    if (!valid(at)) return
    if (!value) { editor.value?.commands.focus(); return }
    const parsed = new DOMParser().parseFromString(editableHtml(value), 'text/html')
    const paragraph = parsed.body.children.length === 1 ? parsed.body.firstElementChild : null
    const link = paragraph?.tagName === 'P' && paragraph.childElementCount === 1 ? paragraph.querySelector('a') : null
    const href = link?.getAttribute('href')
    if (href && !link?.querySelector('img') && at.from !== at.to) editor.value!.chain().setTextSelection({ from: at.from, to: at.to }).setLink({ href }).focus().run()
    else insertAt(at, value)
  } finally { release(at) }
}
function finishInternalSelection(value: string): void {
  const at = linkAnchor
  linkAnchor = undefined; linkOpen.value = false
  if (at) insertInternalResources(value, at)
}
async function openInternal(): Promise<void> {
  if (readonly) return
  release(linkAnchor); linkAnchor = anchor(); const at = linkAnchor
  if (pickResources) {
    try {
      const value = await pickResources()
      insertInternalResources(value, at)
    } catch { $q.notify({ type: 'negative', message: t('richEditor.resources.failed') }) }
    finally { release(at) }
    return
  }
  linkOpen.value = true
}
function navigate(uri: string): void {
  if (uri.startsWith('blob:')) { imagePreview.value = uri; return }
  if (navigateDocument(uri)) return
  const target = richLinkTarget(uri, '', resourceAgentId)
  if (target) { resourceDetail.value = target; return }
  const attachment = attachmentReference(uri)
  if (attachment) { emit('open-attachment', ...attachment); return }
  const href = richLinkHref(uri)
  if (href) window.open(href, '_blank', 'noopener,noreferrer')
}
function selectionUri(): string { const attrs = selectedAttributes.value; if (attrs.html) return new DOMParser().parseFromString(attrs.html, 'text/html').querySelector('a')?.getAttribute('href') ?? attrs.src ?? ''; return editor.value?.getAttributes('link').href ?? '' }
function openSelection(): void { const attrs = selectedAttributes.value; navigate(attrs.src ?? selectionUri()) }
function openSelectionDialog(): void {
  const uri = selectedDocumentUri.value
  if (!uri) return
  resourceDetail.value = richLinkTarget(uri)
}
async function openContextMenu(event: MouseEvent): Promise<void> {
  if (mobileDocument.value) return
  if (readonly) { event.preventDefault(); event.stopPropagation(); return }
  const current = editor.value, target = event.target
  if (!current || current.isDestroyed || sourceMode.value || !(target instanceof Element) || !current.view.dom.contains(target)) return
  const object = target.closest('.galaris-image-object, blockquote.galaris-link-card, .embedded-code-widget, [data-math="inline"], [data-math="block"]')
  const request = ++pointerRequest
  pointerMenu.value?.hide()
  pointerSelection = undefined
  if (object) {
    const position = current.view.posAtDOM(object, 0)
    const node = current.state.doc.nodeAt(position)
    if (!node || !NodeSelection.isSelectable(node)) return
    current.commands.setNodeSelection(position)
  } else {
    const position = current.view.posAtCoords({ left: event.clientX, top: event.clientY })?.pos
    if (position === undefined) return
    const { selection } = current.state
    // Keep multi-cell and text selections when the pointer is inside them.
    if (!target.closest('.selectedCell') && (selection.empty || position < selection.from || position > selection.to)) current.commands.setTextSelection(position)
  }
  selectContextLink(target)
  selectedCardImage.value = target instanceof HTMLImageElement ? target.dataset.editorAttachment ?? target.dataset.editorPreview ?? '' : ''
  await showContextMenu(event, request)
}
async function openKeyboardContextMenu(): Promise<void> {
  const current = editor.value
  if (readonly || !current || current.isDestroyed || sourceMode.value) return
  const request = ++pointerRequest
  pointerMenu.value?.hide()
  pointerSelection = undefined
  const anchor = window.getSelection()?.anchorNode
  selectContextLink(anchor instanceof Element ? anchor : anchor?.parentElement)
  const box = current.view.coordsAtPos(current.state.selection.from)
  await showContextMenu(new MouseEvent('contextmenu', { clientX: box.left, clientY: box.bottom }), request)
  await nextTick()
  const menuElement = document.getElementById(pointerMenuId)
  if (request === pointerRequest && pointerMenuOpen.value) menuElement?.querySelector<HTMLElement>('[role="menuitem"], [role="menuitemcheckbox"]')?.focus()
}
function selectContextLink(target: Element | null | undefined): void {
  const current = editor.value
  if (current && target && current.view.dom.contains(target) && target.closest('a') && current.state.selection.empty && !current.isActive('link')) current.commands.extendMarkRange('link')
}
function queueContextFocus(): void { restoreContextOnHide = true }
async function restoreContextFocus(): Promise<void> {
  if (!restoreContextOnHide) return
  restoreContextOnHide = false
  await nextTick()
  editor.value?.view.focus()
}
async function showContextMenu(event: MouseEvent, request: number): Promise<void> {
  const current = editor.value
  if (!current || current.isDestroyed) return
  pointerMenuY.value = event.clientY
  pointerTextContext.value = !readonly && !(current.state.selection instanceof NodeSelection) && !current.isActive('codeBlock')
  if (!activeContext.value && !pointerTextContext.value) return
  event.preventDefault()
  event.stopPropagation()
  current.view.focus()
  const { doc, selection } = current.state
  await nextTick()
  if (request === pointerRequest && editor.value === current && !current.isDestroyed && current.state.doc === doc && current.state.selection.eq(selection)) {
    pointerSelection = selection
    pointerMenu.value?.show(event)
  }
}
function editorClick(event: MouseEvent): void {
  if (!(event.target instanceof Element) || !event.target.closest('[data-editor-surface]')) return
  selectedCardImage.value = event.target instanceof HTMLImageElement ? event.target.dataset.editorAttachment ?? event.target.dataset.editorPreview ?? '' : ''
  if (readonly && event.target.closest('.galaris-image-object')) return
  if ((readonly || profile === 'document') && event.target.closest('.q-btn, input, select, textarea, [data-document-player]')) return
  const link = event.target.closest('[data-editor-surface] a')
    ?? (readonly || profile === 'document' ? event.target.closest('blockquote.galaris-link-card')?.querySelector('a') : null)
  if (!link) return
  const uri = link.getAttribute('data-rich-reference') ?? link.getAttribute('href') ?? ''
  const card = link.closest('blockquote.galaris-link-card')
  const targetKind = richLinkTarget(uri)?.kind
  const cardTitle = card && card.querySelector('a') === link && (documentUriFromLink(uri, window.location.origin) || targetKind)
  event.preventDefault()
  if (profile === 'document' || event.ctrlKey || event.metaKey || readonly || cardTitle) {
    event.stopPropagation()
    navigate(uri)
  }
}
function insertBeside(after: boolean): void {
  const current = editor.value
  if (!current || readonly) return
  const { selection } = current.state
  if (selection instanceof NodeSelection && selection.node.type.name === 'inlineMath') {
    current.commands.setTextSelection(after ? selection.to : selection.from)
    current.view.focus()
    return
  }
  let position: number
  if (selection instanceof NodeSelection && selection.node.isBlock) position = after ? selection.to : selection.from
  else {
    const { $from } = selection
    let depth = $from.depth
    while (depth > 0 && !['codeBlock', 'table', 'tableFigure'].includes($from.node(depth).type.name)) depth--
    if (!depth) return
    if (depth > 1 && $from.node(depth - 1).type.name === 'tableFigure') depth--
    position = after ? $from.after(depth) : $from.before(depth)
  }
  current.chain().insertContentAt(position, { type: 'paragraph' }).setTextSelection(position + 1).run()
  current.view.focus()
}
function insertAtObjectEdge(): boolean {
  const current = editor.value
  if (!current) return false
  const { selection } = current.state
  // Linked resource cards keep Alt+Enter for opening their target.
  if (selection instanceof NodeSelection && selection.node.isBlock && selection.node.type.name !== 'resourceCard') { insertBeside(true); return true }
  if (!selection.empty) return false
  const { $from } = selection
  for (let depth = $from.depth; depth > 0; depth--) {
    const node = $from.node(depth)
    if (!['table', 'codeBlock'].includes(node.type.name)) continue
    let first: number | undefined, last: number | undefined
    if (node.isTextblock) { first = $from.start(depth); last = $from.end(depth) }
    else node.descendants((child, offset) => {
      if (child.isTextblock) { const start = $from.before(depth) + offset + 2; first ??= start; last = start + child.content.size }
    })
    if (selection.from !== first && selection.from !== last) return false
    insertBeside(selection.from !== first); return true
  }
  return false
}
function clearDirectFormat(): void {
  const current = editor.value
  if (!current) return
  const { selection, schema } = current.state, tr = current.state.tr
  // Links, paragraph styles and embedded objects carry meaning, not direct formatting.
  for (const mark of Object.values(schema.marks)) {
    if (mark.name === 'link') continue
    tr.removeMark(selection.from, selection.to, mark); tr.removeStoredMark(mark)
  }
  tr.doc.nodesBetween(selection.from, selection.to, (node, pos) => {
    if (node.attrs.editorialStyle || node.attrs.textAlign) tr.setNodeMarkup(pos, undefined, { ...node.attrs, editorialStyle: null, textAlign: null })
  })
  current.view.dispatch(tr)
  current.view.focus()
}
function editorKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    if (findOpen.value) { event.preventDefault(); event.stopPropagation(); closeFind() }
    else fullscreen.value = false
    return
  }
  const findShortcut = profile === 'document' ? documentShortcut(event, altGraphPressed)?.[2] === 'find'
    : (event.ctrlKey || event.metaKey) && !event.shiftKey && !event.altKey && event.key.toLowerCase() === 'f'
  if (!event.defaultPrevented && !event.isComposing && !isAltGraphInput(event, altGraphPressed) && findShortcut) {
    event.preventDefault(); showDialog('find'); return
  }
  if (!event.defaultPrevented && event.altKey && event.key === 'Enter') {
    const link = event.target instanceof Element ? event.target.closest('a') : null
    const uri = link?.getAttribute('data-rich-reference') ?? link?.getAttribute('href') ?? selectionUri()
    if (uri) { event.preventDefault(); navigate(uri) }
  }
}
function removeSelected(): void { if (selectedType.value === 'resourceCard' || selectedType.value.includes('Image')) editor.value?.commands.deleteSelection(); else editor.value?.chain().focus().unsetLink().run() }
const busyCard = ref(false), savedCards = new Map<string, string>()
async function convertCard(): Promise<void> {
  const current = editor.value; if (!current || readonly || busyCard.value) return
  if (current.isActive('link')) current.commands.extendMarkRange('link')
  const at = anchor(), uri = selectionUri(), original = current.state.doc.slice(at.from, at.to).toJSON(); busyCard.value = true
  try { let markup: string; if (selectedType.value === 'resourceCard') { const saved = String(selectedAttributes.value.html); savedCards.set(uri, saved); const link = document.createElement('a'); link.href = uri; link.textContent = richLinkTarget(uri) ? new DOMParser().parseFromString(saved, 'text/html').querySelector('a')?.textContent ?? uri : uri; markup = '<p>' + link.outerHTML + '</p>' } else markup = savedCards.get(uri) ?? await (richLinkHasCard(uri) ? richLinkCard(uri, resourceAgentId, referenceFormatting()) : createLinkCard!(uri))
    if (valid(at) && JSON.stringify(current.state.doc.slice(at.from, at.to).toJSON()) === JSON.stringify(original)) insertAt(at, markup)
  } catch { $q.notify({ type: 'warning', message: t('richEditor.resources.cardUnavailable') }) } finally { release(at); busyCard.value = false }
}
const dialogOpen = ref(false), dialog = ref('link'); let dialogAnchor: Anchor | undefined
const imageStyles = computed(() => ['inline', 'wrapText', 'breakText'].map(value => ({ value, label: t('richEditor.imageStyles.' + value) })))
const listStyles = computed(() => (editor.value?.isActive('orderedList') ? ['decimal', 'lower-roman', 'upper-roman', 'lower-alpha', 'upper-alpha'] : ['disc', 'circle', 'square']).map(value => ({ value, label: t('richEditor.listStyles.' + value) })))
const fields = ref({ url: '', text: '', search: '', replace: '', matchCase: false, wholeWords: false, alt: '', caption: '', width: '', height: '', background: '', border: '', color: '#087FF5', imageStyle: 'breakText', imageLink: '', start: '1', reversed: false, listStyle: 'decimal' })
function showDialog(kind: string): void {
  const current = editor.value; if (!current) return
  if (kind === 'find') {
    if (sourceMode.value) return
    findOpen.value = true
    nextTick(() => { searchInput.value?.focus(); searchInput.value?.select() })
    return
  }
  if (kind === 'link' && current.isActive('link')) current.commands.extendMarkRange('link')
  release(dialogAnchor); dialogAnchor = anchor(); dialog.value = kind
  fields.value.url = selectionUri(); fields.value.text = current.state.doc.textBetween(dialogAnchor.from, dialogAnchor.to)
  const attrs = selectedAttributes.value
  if (kind === 'image') { const doc = new DOMParser().parseFromString(attrs.html ?? '', 'text/html'), image = doc.querySelector('img'); fields.value.imageLink = image?.closest('a')?.getAttribute('href') ?? ''; fields.value.alt = image?.alt ?? ''; fields.value.caption = doc.querySelector('figcaption')?.textContent ?? ''; fields.value.width = doc.querySelector<HTMLElement>('figure, span.image-inline')?.style.width || image?.style.width || ''; fields.value.imageStyle = doc.querySelector('.image-style-side') ? 'wrapText' : doc.querySelector('figure') ? 'breakText' : 'inline' }
  if (kind === 'listProperties') { const ordered = current.isActive('orderedList'), list = current.getAttributes(ordered ? 'orderedList' : 'bulletList'); const style = document.createElement('div'); style.setAttribute('style', list.editorialStyle ?? ''); fields.value.listStyle = style.style.listStyleType || (ordered ? 'decimal' : 'disc'); fields.value.start = String(list.start ?? 1); fields.value.reversed = Boolean(list.reversed) }
  if (kind === 'tableProperties' || kind === 'cellProperties') {
    const type = kind === 'tableProperties' ? 'table' : current.isActive('tableHeader') ? 'tableHeader' : 'tableCell'
    const style = document.createElement('div'); style.setAttribute('style', current.getAttributes(type).editorialStyle ?? '')
    fields.value.width = style.style.width; fields.value.height = style.style.height; fields.value.border = style.style.border; fields.value.background = style.style.backgroundColor
    fields.value.caption = ''
    const { $from } = current.state.selection
    for (let depth = $from.depth; depth > 0; depth--) if ($from.node(depth).type.name === 'tableFigure') {
      const last = $from.node(depth).lastChild
      fields.value.caption = last?.type.name === 'caption' ? last.textContent : ''
      break
    }
  }
  dialogOpen.value = true
}
function releaseDialog(): void { release(dialogAnchor); dialogAnchor = undefined }
function applyDialog(): void {
  const current = editor.value, at = dialogAnchor; if (!current || !at || !valid(at)) return
  current.commands.setTextSelection({ from: at.from, to: at.to })
  if (dialog.value === 'link') {
    const documentUri = documentUriFromLink(fields.value.url.trim(), window.location.origin) ?? canonicalRichLink(fields.value.url.trim()), uri = documentUri ?? fields.value.url
    if (!validRichLink(uri)) return
    if (documentUri && !fields.value.text) void insertDocumentLink(documentUri, anchor(at.from, at.to))
    else if (at.from !== at.to && fields.value.text === current.state.doc.textBetween(at.from, at.to)) current.chain().focus().setLink({ href: uri }).run()
    else { const link = document.createElement('a'); link.href = uri; link.textContent = fields.value.text || uri; insertAt(at, link.outerHTML) }
  }
  else if (dialog.value === 'fontColor') current.chain().focus().setColor(fields.value.color).run()
  else if (dialog.value === 'backgroundColor') current.chain().focus().setBackgroundColor(fields.value.color).run()
  else if (dialog.value === 'specialCharacters') current.chain().focus().insertContent({ type: 'text', text: fields.value.text }).run()
  else if (dialog.value === 'image') {
    const node = current.state.doc.nodeAt(at.from); if (!node) return
    const doc = new DOMParser().parseFromString(node.attrs.html, 'text/html'), image = doc.querySelector('img')!; image.alt = fields.value.alt
    const previousFigure = doc.querySelector('figure')
    const figure = doc.createElement('figure'); figure.className = 'image'
    alignImage(figure, previousFigure ? imageAlignment(previousFigure) : fields.value.imageStyle === 'wrapText' ? 'right' : 'center', fields.value.imageStyle === 'wrapText')
    if (fields.value.imageLink && !validRichLink(fields.value.imageLink)) return
    const link = fields.value.imageLink ? doc.createElement('a') : null
    if (link) { link.setAttribute('href', fields.value.imageLink); link.append(image) }
    const width = /^\d+$/.test(fields.value.width) ? fields.value.width + 'px' : fields.value.width
    if (fields.value.imageStyle === 'inline') image.style.width = width
    else {
      if (width) { figure.style.width = width; figure.classList.add('image_resized') }
      image.style.width = width ? '100%' : ''
    }
    figure.append(link ?? image)
    if (fields.value.caption) { const caption = doc.createElement('figcaption'); caption.textContent = fields.value.caption; figure.append(caption) }
    const markup = fields.value.imageStyle === 'inline' ? (link ?? image).outerHTML : figure.outerHTML
    current.commands.insertContentAt({ from: at.from, to: at.from + node.nodeSize }, inputHtml(markup))
  } else if (dialog.value === 'listProperties') { const type = current.isActive('orderedList') ? 'orderedList' : 'bulletList'; current.commands.updateAttributes(type, { start: Math.max(1, Number(fields.value.start) || 1), reversed: fields.value.reversed, editorialStyle: 'list-style-type: ' + fields.value.listStyle }) }
  else if (dialog.value === 'tableProperties' || dialog.value === 'cellProperties') applyTableProperties(current)
  dialogOpen.value = false
}
const tableClasses = computed<string | null>(() => { void revision.value; return editor.value?.getAttributes('table').editorialClass ?? null })
function applyTableStyle(palette?: TablePalette, treatment?: TableTreatment): void {
  const current = editor.value
  if (!current || readonly || !current.isActive('table')) return
  current.view.dispatch(closeHistory(current.state.tr))
  current.chain().focus().updateAttributes('table', { editorialClass: withTableStyle(tableClasses.value, palette, treatment) }).run()
}
function applyTableProperties(current: Editor): void {
  const type = dialog.value === 'tableProperties' ? 'table' : current.isActive('tableHeader') ? 'tableHeader' : 'tableCell'
  const style = document.createElement('div'); style.setAttribute('style', current.getAttributes(type).editorialStyle ?? '')
  for (const key of ['width', 'height', 'background', 'border'] as const) {
    const value = fields.value[key], property = key === 'background' ? 'background-color' : key
    if (value) style.style.setProperty(property, /^\d+$/.test(value) ? value + 'px' : value)
    else style.style.removeProperty(property)
  }
  current.commands.updateAttributes(type, { editorialStyle: style.getAttribute('style') })
  if (dialog.value !== 'tableProperties') return
  const { $from } = current.state.selection
  for (let depth = $from.depth; depth > 0; depth--) {
    const node = $from.node(depth)
    if (node.type.name !== 'table') continue
    const parent = $from.node(depth - 1), caption = fields.value.caption
    const content = caption ? current.schema.nodes.caption!.create(null, current.schema.text(caption)) : null
    const tr = current.state.tr
    if (parent.type.name === 'tableFigure') {
      const start = $from.after(depth), old = parent.lastChild?.type.name === 'caption' ? parent.lastChild : null
      if (content) tr.replaceWith(start, start + (old?.nodeSize ?? 0), content)
      else if (old) tr.delete(start, start + old.nodeSize)
    } else if (content) tr.replaceWith($from.before(depth), $from.after(depth), current.schema.nodes.tableFigure!.create(null, [node, content]))
    if (tr.docChanged) current.view.dispatch(tr)
    break
  }
}
function findMatches(doc: ProseMirrorNode): Array<{ from: number; to: number }> {
  const values: Array<{ from: number; to: number }> = [], search = fields.value.search
  if (!search) return values
  const expression = new RegExp(search.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), fields.value.matchCase ? 'gu' : 'giu')
  doc.descendants((node, position) => {
    if (!node.isTextblock) return
    const text = node.textBetween(0, node.content.size, '', '\ufffc')
    for (const match of text.matchAll(expression)) {
      const offset = match.index
      if (fields.value.wholeWords && (/[\p{L}\p{N}_]$/u.test(text.slice(0, offset)) || /^[\p{L}\p{N}_]/u.test(text.slice(offset + match[0].length)))) continue
      values.push({ from: position + 1 + offset, to: position + 1 + offset + match[0].length })
    }
    return false
  })
  return values
}
const matches = computed(() => {
  void revision.value
  return editor.value ? findMatches(editor.value.state.doc) : []
})
// Query changes redraw temporary highlights without changing the document or undo history.
watch([findOpen, () => fields.value.search, () => fields.value.matchCase, () => fields.value.wholeWords], () => {
  const current = editor.value
  if (current && !current.isDestroyed) current.view.updateState(current.state)
})
function closeFind(): void {
  findOpen.value = false
  editor.value?.commands.focus()
  // Tiptap does not focus a noneditable surface; it remains keyboard-accessible.
  if (readonly) nextTick(() => { if (!findOpen.value) editor.value?.view.dom.focus() })
}
function findNext(): void {
  const current = editor.value
  if (!current) return
  const values = matches.value, from = current.state.selection.to
  const value = values.find(value => value.from >= from) ?? values[0]
  if (!value) return
  current.commands.setTextSelection(value)
  // ProseMirror skips scrolling when focus stays in the search field.
  if (findOpen.value) current.view.dom.querySelector<HTMLElement>('[data-search-current]')?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' })
}
function replaceMatch(): void { if (readonly) return; const value = matches.value.find(value => value.from === editor.value?.state.selection.from) ?? matches.value[0]; if (value) editor.value?.commands.insertContentAt(value, fields.value.replace ? { type: 'text', text: fields.value.replace } : '') }
function replaceAll(): void { const current = editor.value; if (!current || readonly) return; const tr = closeHistory(current.state.tr); for (const match of [...matches.value].reverse()) tr.insertText(fields.value.replace, match.from, match.to); current.view.dispatch(tr) }
const tableCommands = [
  ['addRowBefore', 'vertical_align_top', 'addRowBefore'], ['addRow', 'playlist_add', 'addRowAfter'], ['deleteRow', 'remove', 'deleteRow'],
  ['addColumnBefore', 'first_page', 'addColumnBefore'], ['addColumn', 'view_column', 'addColumnAfter'], ['deleteColumn', 'remove', 'deleteColumn'],
  ['headerRow', 'table_rows', 'toggleHeaderRow'], ['mergeCells', 'call_merge', 'mergeCells'], ['splitCell', 'call_split', 'splitCell'],
  ['tableProperties', 'settings', null], ['cellProperties', 'border_all', null], ['deleteTable', 'delete', 'deleteTable'],
] as const
type TableAction = typeof tableCommands[number][0]
const tableActions = computed(() => {
  void revision.value
  const current = editor.value
  return tableCommands.map(([key, icon, command]) => ({ key, icon, command,
    disabled: !current?.isEditable || !current.isActive('table') || Boolean(command && !current.can()[command]()),
  }))
})
const contextActions = computed(() => {
  void revision.value
  const actions: Array<{ key: string; icon: string; label: string; disabled: boolean; run: () => void }> = []
  const add = (key: string, icon: string, label: string, run: () => void, disabled = false): void => { actions.push({ key, icon, label: t('richEditor.' + label), disabled, run }) }
  if (activeContext.value?.kind === 'code') {
    add('lines', 'format_list_numbered', 'codeTools.lineNumbers', () => { editor.value?.commands.updateAttributes('codeBlock', { lines: !selectedAttributes.value.lines }) }, readonly)
    add('wrap', 'wrap_text', 'codeTools.wrap', () => { editor.value?.commands.updateAttributes('codeBlock', { nowrap: !selectedAttributes.value.nowrap }) }, readonly)
    add('copy', editorialIcon('copy', 'content_copy'), 'codeTools.copy', copyCode)
  } else if (activeContext.value?.kind === 'table') {
    for (const item of tableActions.value) add(item.key, editorialIcon(item.key, item.icon), item.key, () => tableAction(item.key), item.disabled)
  } else if (activeContext.value?.kind === 'equation') {
    add('edit', editorialIcon('edit', 'edit'), 'equation.edit', () => openMath('inline', editor.value?.state.selection.from))
    for (const key of ['cut', 'copy'] as const) add(key, editorialIcon(key, key === 'cut' ? 'content_cut' : 'content_copy'), 'clipboard.' + key, () => { void clipboardAction(key) })
    add('remove', 'delete', 'equation.remove', () => {
      const current = editor.value
      if (!current || readonly || !(current.state.selection instanceof NodeSelection) || !['inlineMath', 'blockMath'].includes(current.state.selection.node.type.name)) return
      current.view.dispatch(closeHistory(current.state.tr))
      current.chain().deleteSelection().focus().run()
    })
  } else if (activeContext.value?.kind === 'resource') {
    add('open', editorialIcon('open', 'open_in_new'), 'open', openSelection)
    add('copyReference', 'link', 'copy', () => { void copyToClipboard(selectionUri()).then(() => $q.notify({ type: 'positive', message: t('common.copied') })).catch(() => $q.notify({ type: 'negative', message: t('richEditor.copyError') })) })
    if (selectedDocumentUri.value) add('openInDialog', 'open_in_new', 'openInDialog', openSelectionDialog)
    if (selectedType.value !== 'resourceCard') add('edit', editorialIcon('edit', 'edit'), selectedType.value.includes('Image') ? 'imageProperties' : 'link', () => showDialog(selectedType.value.includes('Image') ? 'image' : 'link'), readonly)
    if (selectedCardImage.value) add('image', editorialIcon('image', 'image'), 'resources.openImage', () => navigate(selectedCardImage.value))
    if (canConvertCard.value) add('convert', 'view_agenda', 'resources.' + (selectedType.value === 'resourceCard' ? 'asUrl' : 'asCard'), convertCard, readonly || busyCard.value)
    add('remove', 'delete', selectedType.value === 'resourceCard' || selectedType.value.includes('Image') ? 'remove' : 'removeLink', removeSelected, readonly)
  }
  if (canInsertBeside.value && !readonly) {
    add('insertBefore', editorialIcon('insertBefore', 'vertical_align_top'), selectedType.value === 'inlineMath' ? 'equation.before' : 'insertBefore', () => insertBeside(false))
    add('insertAfter', editorialIcon('insertAfter', 'vertical_align_bottom'), selectedType.value === 'inlineMath' ? 'equation.after' : 'insertAfter', () => insertBeside(true))
  }
  return actions
})
function runContextAction(key: string): void { const item = contextActions.value.find(item => item.key === key); if (item && !item.disabled) item.run() }
function runPointerTextAction(key: string, value?: string): void {
  pointerMenu.value?.hide()
  action(key, value)
}
const clipboardActions = ['cut', 'copy', 'paste'] as const
async function clipboardAction(key: typeof clipboardActions[number]): Promise<void> {
  const current = editor.value
  if (!current || readonly || sourceMode.value) return
  const { doc, selection } = current.state, started = generation
  pointerMenu.value?.hide()
  const unchanged = (): boolean => editor.value === current && !current.isDestroyed && generation === started && !readonly && !sourceMode.value && current.state.doc === doc && current.state.selection.eq(selection)
  try {
    if (key === 'paste') {
      const items = navigator.clipboard.read ? await navigator.clipboard.read() : []
      const rich = items.find(item => item.types.includes('text/html'))
      const plain = items.find(item => item.types.includes('text/plain'))
      const markup = rich ? await (await rich.getType('text/html')).text() : undefined
      const text = !rich ? plain ? await (await plain.getType('text/plain')).text() : await navigator.clipboard.readText() : ''
      if (!unchanged()) return
      current.view.focus()
      const transfer = new DataTransfer()
      if (markup) transfer.setData('text/html', markup)
      if (text) transfer.setData('text/plain', text)
      if (handleTransfer(transfer, selection.from, new ClipboardEvent('paste', { clipboardData: transfer }))) return
      if (markup) current.view.pasteHTML(editableHtml(markup))
      else if (text) current.view.pasteText(text)
    } else {
      if (selection.empty) return
      const { dom, text } = current.view.serializeForClipboard(selection.content())
      if (navigator.clipboard?.write && typeof ClipboardItem !== 'undefined') await navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([dom.innerHTML], { type: 'text/html' }), 'text/plain': new Blob([text], { type: 'text/plain' }),
      })])
      else await copyToClipboard(text)
      // A delayed clipboard response must never cut another document or selection.
      if (unchanged()) {
        if (key === 'cut') {
          current.view.dispatch(closeHistory(current.state.tr))
          current.chain().focus().deleteSelection().run()
        }
        else current.view.focus()
      }
    }
  } catch { if (unchanged()) $q.notify({ type: 'negative', message: t('richEditor.clipboard.failed') }) }
}
async function runPointerAction(key: string): Promise<void> {
  pointerMenu.value?.hide()
  runContextAction(key)
  if (key === 'insertBefore' || key === 'insertAfter') {
    await nextTick()
    editor.value?.view.focus()
  }
}
function tableAction(key: TableAction): void {
  const current = editor.value, item = tableActions.value.find(item => item.key === key)
  if (!current || readonly || !item || item.disabled) return
  if (!item.command) { showDialog(key); return }
  current.view.dispatch(closeHistory(current.state.tr))
  current.chain().focus()[item.command]().run()
}
function indent(amount: number): void { const current = editor.value; if (!current) return; const item = current.isActive('checklistItem') ? 'checklistItem' : current.isActive('listItem') ? 'listItem' : null; if (item) { amount > 0 ? current.commands.sinkListItem(item) : current.commands.liftListItem(item); return }; for (const type of ['paragraph', 'heading']) if (current.isActive(type)) { const style = document.createElement('div'); style.setAttribute('style', current.getAttributes(type).editorialStyle ?? ''); const width = Math.max(0, (parseFloat(style.style.marginLeft) || 0) + amount * 40); if (width) style.style.marginLeft = width + 'px'; else style.style.removeProperty('margin-left'); current.commands.updateAttributes(type, { editorialStyle: style.getAttribute('style') }); break } }
function action(key: string, value?: string): void {
  const current = editor.value; if (!current) return
  if (key === 'source') { if (profile === 'document') return; if (sourceMode.value) { applyingExternal = true; current.commands.setContent(editableHtml(sourceDraft.value), { emitUpdate: false }); applyingExternal = false }; sourceDraft.value = html(); stop(); sourceMode.value = !sourceMode.value; return }
  if (key === 'fullscreen') { fullscreen.value = !fullscreen.value; return }
  if (key === 'outline') { outlineOpen.value = !outlineOpen.value; return }
  if (key === 'selectAll') { current.commands.selectAll(); return }
  if (key === 'layout.full') { layout.value = layout.value === 'fixed' ? 'full' : 'fixed'; return }
  if (key === 'help') { showDialog('help'); return }
  if (key === 'shortcuts.toolbarFocus' || key === 'shortcuts.contextFocus') {
    if (key === 'shortcuts.contextFocus') void openKeyboardContextMenu()
    else root.value?.querySelector<HTMLElement>('[role="toolbar"] button')?.focus()
    return
  }
  if (key === 'print' || key === 'exportPdf' || key === 'resources.documentExportBundle') { void exportAction(key); return }
  if (key === 'share.action') { void prepareShare(); return }
  if (key === 'read') { if (personalVoice?.controls.value.reading) personalVoice.controls.value.togglePause(); else personalVoice?.controls.value.read(window.getSelection()?.isCollapsed ? undefined : selectedHtml()); return }
  if (key === 'stopReading') { personalVoice?.stop(); return }
  if (key === 'find' && !sourceMode.value) { if (findOpen.value) closeFind(); else showDialog('find'); return }
  if (readonly || sourceMode.value) return
  current.view.dispatch(closeHistory(current.state.tr))
  const chain = current.chain()
  if (!current.view.hasFocus()) chain.focus()
  switch (key) {
    case 'equation.inline': openMath('inline'); break
    case 'equation.block': openMath('block'); break
    case 'bold': chain.toggleBold().run(); break; case 'italic': chain.toggleItalic().run(); break; case 'underline': chain.toggleUnderline().run(); break; case 'strike': chain.toggleStrike().run(); break; case 'subscript': chain.toggleSubscript().run(); break; case 'superscript': chain.toggleSuperscript().run(); break; case 'shortcuts.inlineCode': chain.toggleCode().run(); break
    case 'undo': chain.undo().run(); break; case 'redo': chain.redo().run(); break
    case 'removeFormat': case 'shortcuts.clearDirectFormat': clearDirectFormat(); break
    case 'shortcuts.insertText': if (value) chain.insertContent({ type: 'text', text: value }).run(); break
    case 'shortcuts.clearList': if (current.isActive('checklist')) chain.toggleList('checklist', 'checklistItem').run(); else if (current.isActive('orderedList')) chain.toggleOrderedList().run(); else if (current.isActive('bulletList')) chain.toggleBulletList().run(); break
    case 'shortcuts.table': if (current.isActive('table')) showDialog('tableProperties'); else action('insertTable'); break
    case 'shortcuts.heading': {
      if (value === '0') { if (!current.isActive('paragraph')) chain.setParagraph().run() }
      else if (!current.isActive('heading', { level: Number(value) })) chain.setHeading({ level: Number(value) as 1 | 2 | 3 | 4 | 5 | 6 }).run()
      break
    }
    case 'checklist': chain.toggleList('checklist', 'checklistItem').run(); break
    case 'bulletList': chain.toggleBulletList().run(); break; case 'orderedList': chain.toggleOrderedList().run(); break; case 'quote': chain.toggleBlockquote().run(); break; case 'code': chain.toggleNode('codeBlock', 'paragraph').run(); break; case 'separator': chain.setHorizontalRule().run(); break
    case 'heading': if (value === '0') chain.setParagraph().run(); else chain.toggleHeading({ level: Number(value) as 1 | 2 | 3 | 4 | 5 | 6 }).run(); break
    case 'callout': {
      if (value && current.isActive('blockquote', { editorialClass: 'galaris-callout galaris-callout-' + value })) { action('callout', ''); break }
      if (!value) {
        const ranges: Array<{ from: number; to: number }> = []
        current.state.doc.nodesBetween(current.state.selection.from, current.state.selection.to, (node, pos) => { if (node.type.name === 'blockquote') { ranges.push({ from: pos, to: pos + node.nodeSize }); return false } })
        chain.command(({ tr }) => { for (const range of ranges.reverse()) { const node = tr.doc.nodeAt(range.from); if (node) tr.replaceWith(range.from, range.to, node.content) }; return true }).run()
        break
      }
      let existing = false
      const tr = current.state.tr
      current.state.doc.nodesBetween(current.state.selection.from, current.state.selection.to, (node, pos) => {
        if (node.type.name !== 'blockquote') return
        existing = true; tr.setNodeMarkup(pos, undefined, { ...node.attrs, editorialClass: 'galaris-callout galaris-callout-' + value }); return false
      })
      if (existing) current.view.dispatch(tr)
      else chain.wrapIn('blockquote', { editorialClass: 'galaris-callout galaris-callout-' + value }).run()
      break
    }
    case 'alignment': {
      if (current.isActive('documentImage') && (value === 'left' || value === 'center' || value === 'right')) {
        const image = new DOMParser().parseFromString(current.getAttributes('documentImage').html, 'text/html').body.firstElementChild as HTMLElement
        alignImage(image, value)
        chain.updateAttributes('documentImage', { html: image.outerHTML }).run()
      } else chain.setTextAlign(value!).run()
      break
    }
    case 'fontFamily': value ? chain.setFontFamily(value).run() : chain.unsetFontFamily().run(); break; case 'fontSize': chain.setFontSize(value + 'px').run(); break; case 'highlight': chain.toggleHighlight({ color: '#FFE610' }).run(); break
    case 'shortcuts.indent': indent(1); break; case 'shortcuts.outdent': indent(-1); break
    case 'galarisLink': void openInternal(); break; case 'resources.uploadFile': fileInput.value?.click(); break
    case 'insertTable': chain.insertContent({ type: 'tableFigure', content: [{ type: 'table', content: Array.from({ length: 3 }, () => ({ type: 'tableRow', content: Array.from({ length: 3 }, () => ({ type: 'tableCell', content: [{ type: 'paragraph' }] })) })) }] }).run(); break
    case 'dictate': personalVoice?.controls.value.toggleDictation(); break
    default: showDialog(key)
  }
}
function selectedHtml(): string { const current = editor.value; if (!current) return ''; const container = document.createElement('div'); const range = window.getSelection(); if (range?.rangeCount) container.append(range.getRangeAt(0).cloneContents()); return sanitizeRichHtml(container.innerHTML, profile) }
function syncCollapsedSelection(): void {
  const current = editor.value, selection = window.getSelection()
  if (!current?.isEditable || !selection?.isCollapsed || !selection.anchorNode || !current.view.dom.contains(selection.anchorNode)) return
  if (current.state.selection.toJSON().type === 'cell') return
  // selectionchange may arrive after the next key event. A click in ordinary
  // text must leave an atomic object before typing can replace that object.
  if (current.state.selection instanceof NodeSelection && (selection.anchorNode.nodeType !== Node.TEXT_NODE
    || selection.anchorNode.parentElement?.closest('[contenteditable="false"]'))) return
  const position = current.view.posAtDOM(selection.anchorNode, selection.anchorOffset)
  if (position !== current.state.selection.from) current.commands.setTextSelection(position)
}
function syncKeyboardSelection(): void {
  const current = editor.value, selection = window.getSelection()
  if (!current?.isEditable || !selection) return
  if (selection.isCollapsed) { syncCollapsedSelection(); return }
  if (current.state.selection instanceof NodeSelection || current.state.selection.toJSON().type === 'cell') return
  const { anchorNode, focusNode, anchorOffset, focusOffset } = selection
  if (!anchorNode || !focusNode || !current.view.dom.contains(anchorNode) || !current.view.dom.contains(focusNode)) return
  // Native Shift+End/arrow selections can reach the DOM before selectionchange
  // reaches ProseMirror. Apply the next formatting command to the visible range.
  const from = current.view.posAtDOM(anchorNode, anchorOffset), to = current.view.posAtDOM(focusNode, focusOffset)
  if (from !== current.state.selection.anchor || to !== current.state.selection.head) current.commands.setTextSelection({ from, to })
}
function syncReadingSelection(): void { const selection = editor.value?.state.selection; if (selection instanceof TextSelection && !selection.empty) syncCollapsedSelection() }
function editSource(value: string): void { sourceDraft.value = value; publish(profile === 'document' ? restoreInteractiveHtml(editableHtml(value)) : editableHtml(value)) }
async function copyCode(): Promise<void> { const current = editor.value; if (!current) return; try { await copyToClipboard(current.state.selection.$from.parent.textContent); $q.notify({ type: 'positive', message: t('richEditor.codeTools.copied') }) } catch { $q.notify({ type: 'negative', message: t('richEditor.codeTools.copyFailed') }) } }
function setCodeLanguage(language: string): void { const current = editor.value; if (!current || readonly) return; current.view.dispatch(closeHistory(current.state.tr)); current.chain().focus().updateAttributes('codeBlock', { language }).run() }
async function exportAction(key: string): Promise<void> { if (exportJobs.has(key)) return; const pending = request(); exportJobs.set(key, pending); exportBusy.value = [...exportJobs.keys()]; try { const content = sourceMode.value ? sourceDraft.value : html(), title = documentTitle || ariaLabel || t('richEditor.content'); if (key === 'print') await printDocument(content, title, pending.signal, resolveImage, renderedResolver.value); else if (key === 'exportPdf' && exportPdf) await exportDocumentPdf(content, title, pending.signal, exportPdf, resolveImage, renderedResolver.value); else if (key === 'resources.documentExportBundle' && exportBundle) await exportDocumentBundle(withAttachmentInventory(content, attachments, t('richEditor.resources.attachments')), title, pending.signal, exportBundle, resolveImage, renderedResolver.value) } catch { if (!pending.signal.aborted) $q.notify({ type: 'negative', message: t(key === 'print' ? 'richEditor.printFailed' : key === 'exportPdf' ? 'richEditor.exportPdfFailed' : 'richEditor.resources.exportFailed') }) } finally { requests.delete(pending); if (exportJobs.get(key) === pending) { exportJobs.delete(key); exportBusy.value = [...exportJobs.keys()] } } }
const shareOpen = ref(false), sharePreparing = ref(false), sharing = ref(false), shareError = ref(''), shareFile = shallowRef<File | null>(null); let shareRequest: AbortController | undefined
const nativeShareData = computed<ShareData | null>(() => { if (!shareFile.value || !navigator.share || !navigator.canShare) return null; const files = [shareFile.value]; for (const data of [{ files, title: documentTitle, ...(documentUrl ? { url: documentUrl } : {}) }, { files, title: documentTitle, ...(documentUrl ? { text: documentUrl } : {}) }, { files }]) if (navigator.canShare(data)) return data; return null })
function cancelShare(): void { shareRequest?.abort(); shareFile.value = null; shareError.value = ''; sharePreparing.value = false }
async function prepareShare(): Promise<void> { if (!exportPdf) return; cancelShare(); const pending = request(); shareRequest = pending; shareOpen.value = true; sharePreparing.value = true; try { const file = await createDocumentPdf(html(), documentTitle || t('richEditor.content'), pending.signal, exportPdf, resolveImage, renderedResolver.value); if (!pending.signal.aborted) shareFile.value = file } catch { if (!pending.signal.aborted) shareError.value = t('richEditor.exportPdfFailed') } finally { requests.delete(pending); if (shareRequest === pending) sharePreparing.value = false } }
async function shareDocument(): Promise<void> { if (!shareFile.value || sharing.value) return; sharing.value = true; try { if (nativeShareData.value) await navigator.share(nativeShareData.value); else saveBlobAsResource(shareFile.value, shareFile.value.name); shareOpen.value = false } catch (error) { if (!(error instanceof DOMException && error.name === 'AbortError')) shareError.value = t('richEditor.share.failed') } finally { sharing.value = false } }
let observer: ResizeObserver | undefined, layoutFrame: number | undefined
let scrollPadding: ReturnType<typeof reserveEditorialToolbarSpace> | undefined
onMounted(() => {
  createEditor(); document.addEventListener('selectionchange', syncReadingSelection)
  document.addEventListener('keydown', trackKeyboardModifiers, true)
  document.addEventListener('keyup', trackKeyboardModifiers, true)
  window.addEventListener('blur', resetKeyboardModifiers)
  if (root.value) scrollPadding = reserveEditorialToolbarSpace(root.value)
  observer = new ResizeObserver(() => {
    if (layoutFrame !== undefined) return
    layoutFrame = requestAnimationFrame(() => {
      layoutFrame = undefined; fits.value = (root.value?.clientWidth ?? 0) >= 210 * 96 / 25.4
      scrollPadding?.update()
      const toolbar = root.value?.querySelector('.editorial-toolbar')
      if (toolbar) {
        root.value?.style.setProperty('--editorial-toolbar-height', toolbar.getBoundingClientRect().height + 'px')
        observer?.observe(toolbar)
      }
    })
  })
  if (root.value) observer.observe(root.value)
})
watch(() => modelValue, value => { if (value === lastEmitted) return; stop(); imageCache.clear(); lastEmitted = value; applyingExternal = true; sourceDraft.value = value; createEditor(); applyingExternal = false })
watch(() => profile, () => { stop(); sourceMode.value = false; createEditor() })
watch(() => resourceAgentId, () => { stop(); imageCache.clear(); createEditor() })
watch(() => readonly, value => {
  objectPreview.value = null
  if (value) stop()
  const current = editor.value
  if (current) {
    current.setEditable(!value, false)
    // Node-view controls also follow permission changes without editing content.
    current.view.dispatch(current.state.tr)
  }
  revision.value++
})
watch(locale, () => { editor.value?.view.dom.setAttribute('aria-label', ariaLabel || t('richEditor.content')); revision.value++ })
watch([effectiveLayout, editor], () => { if (editor.value && profile === 'document') editor.value.view.dom.dataset.documentLayout = effectiveLayout.value })
onBeforeUnmount(() => { stop(); imageCache.clear(); document.removeEventListener('selectionchange', syncReadingSelection); document.removeEventListener('keydown', trackKeyboardModifiers, true); document.removeEventListener('keyup', trackKeyboardModifiers, true); window.removeEventListener('blur', resetKeyboardModifiers); observer?.disconnect(); if (layoutFrame !== undefined) cancelAnimationFrame(layoutFrame); scrollPadding?.dispose(); editor.value?.destroy(); urls.forEach(URL.revokeObjectURL); urls.clear() })
defineExpose({ editor, insertResource, insertDictation })
</script>
