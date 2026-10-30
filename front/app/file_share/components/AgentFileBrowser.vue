<template>
  <div class="file-browser-container" :class="{ 'file-browser-container--compact': selection, 'file-browser-container--dialog': externalControls }">
    <q-card flat bordered class="file-workspace">
    <q-linear-progress v-if="uriLoading" indeterminate color="primary" />
    <q-banner v-if="uriError" role="alert" class="file-error">
      {{ t('files.loadError') }}
      <template #action><q-btn color="negative" :label="t('common.retry')" @click="retryUri && openUri(retryUri)" /></template>
    </q-banner>
    <q-splitter v-model="split" :limits="[18, 45]" :disable="$q.screen.lt.md" class="file-browser" :class="{ 'file-browser--tree-hidden': $q.screen.lt.md && !showTree }">
      <template #before>
      <aside class="file-tree" :aria-label="t('files.tree')">
        <q-spinner v-if="schemesLoading" color="primary" />
        <q-list v-else>
          <q-expansion-item v-for="root in treeNodes" :key="root.id" :model-value="openScheme === root.id"
            :header-class="['file-scheme-header', { 'file-scheme-selected': currentUri.startsWith(root.id) }]"
            hide-expand-icon :toggle-aria-label="root.label" :duration="0" @update:model-value="toggleScheme(root.id, $event)">
            <template #header>
              <div class="file-scheme full-width" :title="root.id">
                <div class="file-scheme-label">{{ root.label }}</div>
                <div class="file-scheme-uri text-caption">{{ root.scheme }}://</div>
              </div>
            </template>
            <div v-if="!root.disabledRoot" class="q-px-sm q-pb-sm">
                <q-spinner v-if="directory(root.id).loading" color="primary" :aria-label="t('files.loading')" />
                <q-tree v-if="root.children?.length" :nodes="root.children" node-key="id" :selected="currentUri" :expanded="expanded" dense no-transition
                  :text-color="$q.dark.isActive ? 'white' : 'dark'" :selected-color="$q.dark.isActive ? 'white' : 'dark'"
                  @update:expanded="expanded = [...$event]" @update:selected="selectTree" @lazy-load="lazyLoad">
                  <template #default-header="scope">
                    <div class="file-tree-entry row items-center no-wrap full-width" :title="scope.node.entry.uri">
                      <q-icon v-if="isSkillPackage(scope.node.entry)" name="psychology" color="primary" size="26px" class="q-mr-xs" />
                      <FolderIcon v-else :expanded="scope.expanded" size="26px" class="q-mr-xs" />
                      <span class="ellipsis">{{ scope.node.label }}</span>
                      <FileEntryActions v-if="!selection" :entry="scope.node.entry" :agent-id="agentId" target=".q-tree__node-header" context-only
                        :open="() => openEntry(scope.node.entry)" :open-code="() => openRepository(scope.node.entry)" @changed="entryChanged" />
                    </div>
                  </template>
                </q-tree>
            </div>
          </q-expansion-item>
        </q-list>
      </aside>
      </template>
      <template #separator>
        <span class="file-splitter-handle" role="separator" tabindex="0" aria-orientation="vertical"
          :aria-label="t('files.resize')" :aria-valuenow="split" aria-valuemin="18" aria-valuemax="45"
          @keydown.left.prevent="split = Math.max(18, split - 5)" @keydown.right.prevent="split = Math.min(45, split + 5)">
          <q-icon name="drag_indicator" size="16px" />
        </span>
      </template>
      <template #after>
      <main class="file-main">
        <q-toolbar class="file-toolbar q-px-xs">
          <q-btn class="lt-md" round outline color="primary" size="sm" icon="account_tree" :aria-label="t('files.toggleTree')" @click="showTree = !showTree">
            <q-tooltip>{{ t('files.toggleTree') }}</q-tooltip>
          </q-btn>
          <nav ref="breadcrumbNav" class="col file-breadcrumbs" :aria-label="t('files.navigation')">
            <q-btn-group v-if="breadcrumbs.length" rounded unelevated>
              <q-btn v-for="(crumb, index) in breadcrumbs" :key="crumb.uri" dense no-caps color="primary" :outline="crumb.uri !== currentUri" :unelevated="crumb.uri === currentUri"
                padding="3px 8px" :icon="index === 0 ? 'storage' : 'folder_open'" :label="crumb.label"
                :aria-pressed="crumb.uri === currentUri" :aria-current="crumb.uri === currentUri ? 'location' : undefined" @click="navigate(crumb.uri)">
                <q-tooltip>{{ crumb.uri }}</q-tooltip>
              </q-btn>
            </q-btn-group>
          </nav>
          <q-btn v-if="!selection" round unelevated color="primary" size="sm" icon="refresh" :aria-label="t('files.refresh')" :disable="!currentUri" :loading="current?.loading" @click="refresh">
            <q-tooltip>{{ t('files.refresh') }}</q-tooltip>
          </q-btn>
        </q-toolbar>
        <q-separator v-if="!selection" />
        <div v-if="selection && !externalControls" class="row items-center no-wrap q-gutter-xs q-ma-xs">
        <q-input v-model="query" dense outlined clearable debounce="250" class="col" :disable="!canSearch" :label="t('files.searchLocation')">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
        <q-btn flat round dense color="primary" icon="refresh" :aria-label="t('files.refresh')" :disable="!currentUri" :loading="current?.loading" @click="refresh">
          <q-tooltip>{{ t('files.refresh') }}</q-tooltip>
        </q-btn>
        </div>
        <div ref="scroll" class="file-scroll" tabindex="0" :aria-label="t('files.title')">
          <FileEntryActions v-if="!selection && consoleDirectory" :entry="consoleDirectory" :agent-id="agentId" target=".file-scroll" context-only
            :open="() => navigate(currentUri)" :open-code="() => openRepository(consoleDirectory!)" />
          <q-banner v-if="schemesError" role="alert" class="file-error">
            <template #avatar><q-icon name="error" color="negative" /></template>
            {{ t('files.loadError') }}
            <template #action><q-btn color="negative" :label="t('common.retry')" @click="loadSchemes" /></template>
          </q-banner>
          <template v-else-if="!currentUri">
            <div v-if="schemesLoading" class="file-state"><q-spinner color="primary" size="32px" :aria-label="t('files.loading')" /></div>
            <div v-else-if="treeNodes.length" class="file-grid" :aria-label="t('files.roots')">
              <FileTile v-for="root in treeNodes" :key="root.id" :entry="root.entry" :agent-id="agentId" :compact="selection" @open="navigate(root.id)" />
            </div>
            <div v-else class="file-state">{{ t('files.noDirectories') }}</div>
          </template>
          <q-banner v-else-if="unlistable" class="file-warning" role="alert">
            <template #avatar><q-icon name="warning" style="color: var(--solaire-orange-accent)" /></template>
            {{ t('files.noListing') }}
          </q-banner>
          <template v-else-if="current">
            <q-banner v-if="current.error" role="alert" class="file-error q-mb-md">
              <template #avatar><q-icon name="error" color="negative" /></template>
              {{ t('files.loadError') }}
              <template #action><q-btn color="negative" :label="t('common.retry')" @click="retry" /></template>
            </q-banner>
            <q-infinite-scroll :key="currentUri + ':' + (query || '')" :scroll-target="scroll || undefined" :disable="current.error || current.incomplete || (current.loaded && !current.cursor)" :offset="180" @load="loadMore">
              <div class="file-grid">
                <div v-for="entry in sortedEntries.filter(entry => !isMailMessage(entry))" :key="`${entry.uri}:${current.version}`" class="file-entry">
                  <FileTile :entry="entry" :agent-id="agentId" :compact="selection" :selectable="selection" :selected="selected.some(value => value.uri === entry.uri)" @open="openEntry" @activate="activateEntry" @select="toggleEntry" @preview="previewEntry" />
                  <FileEntryActions v-if="!selection" :entry="entry" :agent-id="agentId" target=".file-entry" :context-only="$q.screen.lt.md"
                    :open="() => openEntry(entry)" :open-code="() => openRepository(entry)" @changed="entryChanged"
                    :download="!entry.is_collection && entry.capabilities.includes('read') ? () => downloadEntry(entry) : undefined"
                  />
                </div>
              </div>
              <q-list v-if="mailEntries.length" bordered separator :aria-label="t('files.mail.messages')">
                <q-item v-for="entry in mailEntries" :key="entry.uri" clickable :aria-label="t('files.openItem', { name: entry.name || t('files.mail.noSubject') })" @click="openEntry(entry, $event)">
                  <q-item-section v-if="selection" side><q-checkbox :model-value="selected.some(item => item.uri === entry.uri)" :aria-label="t('files.selectItem', { name: entry.name })" @click.stop @update:model-value="(_value, event) => toggleEntry(entry, event)" /></q-item-section>
                  <q-item-section avatar><q-icon :name="entry.metadata?.seen ? 'drafts' : 'markunread'" color="primary" :aria-label="t(entry.metadata?.seen ? 'files.mail.read' : 'files.mail.unread')" /></q-item-section>
                  <q-item-section>
                    <q-item-label :class="{ 'text-weight-bold': !entry.metadata?.seen }">{{ entry.metadata?.subject || t('files.mail.noSubject') }}</q-item-label>
                    <q-item-label caption>{{ entry.metadata?.from_name || entry.metadata?.from_address }}</q-item-label>
                    <q-item-label v-if="entry.modified_at" caption>{{ mailDate(entry.modified_at) }}</q-item-label>
                  </q-item-section>
                  <q-item-section v-if="entry.metadata?.has_attachments" side><q-icon name="attach_file" :aria-label="t('documents.attachments')" /></q-item-section>
                  <q-item-section side>
                    <q-btn v-if="selection" flat round color="primary" icon="visibility" :aria-label="t('files.previewItem', { name: entry.name })" @click.stop="previewEntry(entry)" />
                    <FileEntryActions v-else :entry="entry" :agent-id="agentId" target=".q-item" :context-only="$q.screen.lt.md" :open="() => openEntry(entry)" :download="() => downloadEntry(entry)" />
                  </q-item-section>
                </q-item>
              </q-list>
              <template #loading><div class="q-pa-md text-center"><q-spinner color="primary" size="30px" :aria-label="t('files.loading')" /></div></template>
            </q-infinite-scroll>
            <div v-if="current.loading && !sortedEntries.length" class="file-state"><q-spinner color="primary" size="32px" /></div>
            <div v-else-if="current.loaded && !current.error && !current.cursor && !sortedEntries.length" class="file-state">{{ t('files.empty') }}</div>
            <q-banner v-if="current.incomplete" class="q-mt-md">{{ t('files.incomplete') }}</q-banner>
          </template>
        </div>
      </main>
      </template>
    </q-splitter>
    </q-card>
    <ResourceDetailDialog v-if="target" ref="detail" :target="target" @close="target = null; refresh()" @changed="refresh" />
    <MailMessageDialog v-if="mailMessage && typeof mailMessage.metadata?.mail_message_ref === 'string'" :key="mailMessage.uri" :agent-id="agentId" :reference="mailMessage.metadata.mail_message_ref" :title="mailMessage.name" @close="mailMessage = null" />
    <ResourceAttachments ref="preview" :key="previewKey" :resource-id="String(agentId)" :agent-id="agentId" :attachments="previewEntries"
      :resource-source="previewSource" preview-only @previewing="filePreviewOpen = $event" />
    <FullscreenPreview :model-value="audioPreview !== null" :viewer-label="audioPreview?.name ?? ''" interactive @update:model-value="!$event && (audioPreview = null)">
      <AudioResourcePlayer v-if="audioPreview" :source="audioPreview" />
    </FullscreenPreview>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar, type QTreeNode } from 'quasar'
import { FolderIcon, ResourceAttachments, ResourceDetailDialog, FullscreenPreview, AudioResourcePlayer, browserResourceKind, richLinkTarget, saveBlobAsResource, type ResourceDetailTarget, type AttachmentSource, type ResourceAttachment } from '@/core/util'
import { fileBrowserService, type FileEntry, type FileScheme } from '../services/fileBrowserService'
import { useFileDirectories } from '../browserState'
import { parentDirectory, resourceTarget, resourceLabel, collectionLabel, compareFileEntries, isSkillPackage } from '../presentation'
import FileTile from './FileTile.vue'
import FileEntryActions from './FileEntryActions.vue'
import MailMessageDialog from './MailMessageDialog.vue'

const { agentId, selection = false, initialUri = null, externalControls = false } = defineProps<{ agentId: number; selection?: boolean; initialUri?: string | null; externalControls?: boolean }>()
const selected = defineModel<FileEntry[]>('selected', { default: () => [] })
const query = defineModel<string | null>('query', { default: '' })
const emit = defineEmits<{ confirm: []; navigate: [uri: string, replace: boolean]; previewing: [value: boolean] }>()
const { t, locale } = useI18n()
const $q = useQuasar()
function entryChanged(entry: FileEntry, replacement: string | null): void {
  if (!active) return
  const affected = (uri: string): boolean => uri === entry.uri || entry.is_collection && uri.startsWith(entry.uri.replace(/\/?$/, '/'))
  const previous = currentUri.value
  const parent = parentDirectory(entry.uri)
  invalidate(entry.uri)
  expanded.value = expanded.value.filter(uri => !affected(uri))
  if (affected(previous)) {
    navigate(replacement ? replacement + previous.slice(entry.uri.length) : parent ?? '', true, 'replace')
  }
  if (parent) void load(parent, false, true)
  if (!affected(previous) && previous !== parent) refresh()
}
async function downloadEntry(entry: FileEntry): Promise<void> {
  const blob = await fileBrowserService.content(agentId, entry.uri, false, undefined, true)
  if (active) saveBlobAsResource(blob, entry.name)
}
async function openRepository(entry: FileEntry): Promise<void> {
  const location = currentUri.value, version = previewKey.value, request = ++repositoryOpening
  const workspace = await fileBrowserService.repository(agentId, entry.uri)
  if (active && currentUri.value === location && previewKey.value === version && repositoryOpening === request) target.value = { kind: 'code', id: workspace.id, title: workspace.label, agentId }
}
const { directory, load, invalidate } = useFileDirectories(agentId, selection)
const schemes = ref<FileScheme[]>([])
const schemesLoading = ref(false), schemesError = ref(false)
const currentUri = ref(''), showTree = ref(false), expanded = ref<string[]>([])
const consoleDirectory = computed<FileEntry | null>(() => currentUri.value.startsWith('console://') ? {
  uri: currentUri.value, name: breadcrumbs.value.at(-1)?.label ?? currentUri.value, is_collection: true,
  media_type: 'inode/directory', size: null, capabilities: [],
} : null)
const openScheme = ref<string | null>(null)
const split = ref(24)
const target = ref<ResourceDetailTarget | null>(null)
const mailMessage = ref<FileEntry | null>(null)
const detail = useTemplateRef<{ canLeave?: () => Promise<boolean> }>('detail')
const preview = useTemplateRef<{ openById: (id: string) => Promise<void> }>('preview')
const previewEntries = ref<ResourceAttachment[]>([]), previewKey = ref(0)
const filePreviewOpen = ref(false)
const audioPreview = ref<{ key: string; name: string; load: (signal: AbortSignal) => Promise<Blob> } | null>(null)
const scroll = useTemplateRef<HTMLElement>('scroll')
const breadcrumbNav = useTemplateRef<HTMLElement>('breadcrumbNav')
let schemesRequest: AbortController | undefined
let active = true
let repositoryOpening = 0
let ready = false
const searchState = ref({ entries: [] as FileEntry[], loading: false, loaded: false, error: false, incomplete: false, cursor: null as string | null, version: 0 })
let searchRequest: AbortController | undefined
let uriRequest: AbortController | undefined
const uriLoading = ref(false), uriError = ref(false)
const retryUri = ref(initialUri)
let anchor = ''
const current = computed(() => query.value?.trim() ? searchState.value : currentUri.value ? directory(currentUri.value) : null)
const unlistable = computed(() => schemes.value.some(scheme => `${scheme.scheme}://` === currentUri.value && (!scheme.capabilities.includes('list') || scheme.root_listable === false)))
const sortedEntries = computed(() => (current.value?.entries ?? []).filter(isVisible).sort((a, b) => compareFileEntries(a, b, locale.value)))
const mailEntries = computed(() => sortedEntries.value.filter(isMailMessage))
function isMailMessage(entry: FileEntry): boolean { return entry.uri.startsWith('mail://') && typeof entry.metadata?.mail_message_ref === 'string' }
function mailDate(value: string): string {
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'short' }).format(date) : value
}
const loadedCount = computed(() => schemesError.value || unlistable.value ? 0 : sortedEntries.value.length)
const canSearch = computed(() => !!currentUri.value && !currentUri.value.startsWith('mail://'))
const canRefresh = computed(() => !!currentUri.value)
const refreshing = computed(() => current.value?.loading ?? false)
async function canLeave(): Promise<boolean> { return await detail.value?.canLeave?.() ?? true }
defineExpose({ loadedCount, canLeave, canSearch, canRefresh, refreshing, refresh })
const previewSource: AttachmentSource = {
  content: (entry, convert, signal) => fileBrowserService.content(agentId, entry.id, convert, signal, selection),
  videoUrl: entry => fileBrowserService.videoUrl(agentId, entry.id, selection),
  releaseVideoUrl: fileBrowserService.releaseVideoUrl,
}
function entryLabel(entry: FileEntry): string {
  const scheme = schemes.value.find(scheme => `${scheme.scheme}://` === entry.uri)
  return (scheme && resourceLabel(scheme, t)) || resourceLabel(entry, t) || collectionLabel(entry.uri, t) || scheme?.label || entry.name
}
const breadcrumbs = computed(() => {
  const ancestors = currentUri.value ? directory(currentUri.value).ancestors : []
  if (ancestors.length) {
    return ancestors.map(entry => ({ uri: entry.uri, label: entryLabel(entry) }))
  }
  // Folder UUIDs identify resources; they are never useful navigation labels,
  // including while a direct link is loading or waiting for a retry.
  if (/^document:\/\/folders\/[^/]+\/$/.test(currentUri.value)) {
    const scheme = schemes.value.find(scheme => scheme.scheme === 'document')
    return [{ uri: 'document://', label: scheme ? resourceLabel(scheme, t) ?? scheme.label : t('nav.documents') }]
  }
  const crumbs: { uri: string; label: string }[] = []
  let uri: string | null = currentUri.value
  while (uri) {
    const path = uri.replace(/\/$/, '')
    let label = path.includes('://') && !path.endsWith(':/') ? path.split('/').at(-1) || uri : uri
    try { label = decodeURIComponent(label) } catch { /* Keep the provider's original label. */ }
    const parent = parentDirectory(uri)
    const entry = parent ? directory(parent).entries.find(entry => entry.uri === uri) : undefined
    const scheme = schemes.value.find(scheme => `${scheme.scheme}://` === uri)
    crumbs.unshift({ uri, label: entry ? entryLabel(entry) : (scheme && resourceLabel(scheme, t)) || collectionLabel(uri, t) || label })
    uri = parent
  }
  return crumbs
})
interface BrowserNode extends QTreeNode { id: string; entry: FileEntry; disabledRoot?: boolean; scheme?: string }
function isVisible(entry: FileEntry): boolean {
  if (entry.uri.startsWith('mail://')) return true
  return !entry.name.startsWith('.') && !/^galaris:\/\/goal_cycle(?:\/|$)/.test(entry.uri)
    && !/^galaris:\/\/goal\/[^/]+\/cycles(?:\/|$)/.test(entry.uri)
}
function treeNode(entry: FileEntry, ancestors: Set<string> = new Set()): BrowserNode {
  const state = directory(entry.uri)
  const disabledRoot = schemes.value.some(scheme => `${scheme.scheme}://` === entry.uri && (!scheme.capabilities.includes('list') || scheme.root_listable === false))
  const node: BrowserNode = { id: entry.uri, label: entryLabel(entry), entry, disabledRoot,
    icon: isSkillPackage(entry) ? 'psychology' : entry.is_collection ? 'folder' : 'insert_drive_file',
    lazy: entry.is_collection && !isSkillPackage(entry) && !disabledRoot && !state.loaded }
  if (entry.is_collection && !isSkillPackage(entry) && state.loaded && !ancestors.has(entry.uri) && ancestors.size < 64) {
    const next = new Set([...ancestors, entry.uri])
    node.children = state.entries.filter(child => child.is_collection && isVisible(child)).map(child => treeNode(child, next))
  }
  return node
}
const treeNodes = computed(() => schemes.value.filter(scheme => scheme.capabilities.includes('list') && scheme.root_listable !== false).map(scheme => ({ ...treeNode({ uri: `${scheme.scheme}://`,
  name: scheme.label, label_code: scheme.label_code, is_collection: true, media_type: '', size: null, capabilities: scheme.capabilities }), scheme: scheme.scheme })))
async function loadSchemes(): Promise<void> {
  schemesRequest?.abort()
  const request = new AbortController(); schemesRequest = request
  schemesLoading.value = true; schemesError.value = false
  try { const result = await fileBrowserService.schemes(agentId, request.signal); if (!request.signal.aborted) schemes.value = result }
  catch { if (!request.signal.aborted) schemesError.value = true }
  finally { if (!request.signal.aborted) schemesLoading.value = false }
}
function toggleScheme(uri: string, opened: boolean): void {
  if (opened) { openScheme.value = uri; navigate(uri, false) }
  else if (openScheme.value === uri) openScheme.value = null
}
function navigate(uri: string, closeTree = true, history: false | 'push' | 'replace' = 'push'): void {
  const changed = currentUri.value !== uri
  uriRequest?.abort(); uriLoading.value = false
  uriError.value = false
  target.value = null; mailMessage.value = null; audioPreview.value = null; previewEntries.value = []; previewKey.value++
  query.value = ''
  currentUri.value = uri
  if (changed && history && !selection) emit('navigate', uri, history === 'replace')
  const root = treeNodes.value.find(root => uri.startsWith(root.id))
  openScheme.value = root?.id ?? null
  if (root && root.id !== uri && !root.disabledRoot && !directory(root.id).loaded && !directory(root.id).error) void load(root.id)
  if (scroll.value) scroll.value.scrollTop = 0
  const reveal = async (): Promise<void> => {
    if (!active || currentUri.value !== uri || !directory(uri).loaded) return
    const ancestors: string[] = directory(uri).ancestors.map(entry => entry.uri)
    if (ancestors.length) {
      await Promise.all(ancestors.filter(parent => parent !== uri && !directory(parent).loaded && !directory(parent).error)
        .map(parent => load(parent)))
      if (!active || currentUri.value !== uri) return
    } else {
      for (let current: string | null = uri; current; current = parentDirectory(current)) ancestors.push(current)
    }
    expanded.value = [...new Set([...expanded.value, ...ancestors])]
  }
  if (uri && !unlistable.value && !directory(uri).loaded && !directory(uri).error) void load(uri).then(reveal)
  else void reveal()
  if (closeTree && $q.screen.lt.md) showTree.value = false
}
async function openEntry(entry: FileEntry, event?: Event, metadataFresh = false): Promise<void> {
  repositoryOpening++
  if (!metadataFresh) { uriRequest?.abort(); uriLoading.value = false; uriError.value = false }
  if (selection && !entry.is_collection) { toggleEntry(entry, event); return }
  if (isMailMessage(entry)) { mailMessage.value = entry; return }
  if (!selection && isSkillPackage(entry)) { target.value = resourceTarget(entry, agentId); return }
  if (entry.is_collection) { navigate(entry.uri, true, metadataFresh ? false : 'push'); return }
  target.value = resourceTarget(entry, agentId, locale.value) ?? richLinkTarget(entry.uri, String(entry.metadata?.label ?? entry.name), agentId)
  if (target.value) return
  if (!metadataFresh && /^(file|document|data|messenger|galaris):\/\//.test(entry.uri)) {
    await openUri(entry.uri, false)
    return
  }
  previewEntries.value = [{ id: entry.uri, uri: entry.uri, name: entry.name, media_type: entry.media_type, size_bytes: entry.size ?? 0 }]
  await nextTick()
  if (active) await preview.value?.openById(entry.uri)
}
function toggleEntry(entry: FileEntry, event?: Event): void {
  if (!selection || !entry.is_collection && !entry.capabilities.includes('read')) return
  const mouse = event as MouseEvent | undefined
  if (mouse?.shiftKey && anchor) {
    const entries = sortedEntries.value
    const start = entries.findIndex(value => value.uri === anchor), end = entries.findIndex(value => value.uri === entry.uri)
    if (start >= 0 && end >= 0) {
      const range = entries.slice(Math.min(start, end), Math.max(start, end) + 1).filter(value => value.is_collection || value.capabilities.includes('read'))
      selected.value = [...new Map([...selected.value, ...range].map(value => [value.uri, value])).values()]
      return
    }
  }
  selected.value = selected.value.some(value => value.uri === entry.uri) ? selected.value.filter(value => value.uri !== entry.uri) : [...selected.value, entry]
  anchor = entry.uri
}
async function previewEntry(entry: FileEntry): Promise<void> {
  if (entry.is_collection || !entry.capabilities.includes('read')) return
  if (isMailMessage(entry)) { mailMessage.value = entry; return }
  audioPreview.value = null; previewEntries.value = []; previewKey.value++
  if (browserResourceKind(entry.media_type, entry.name) === 'audio') {
    audioPreview.value = { key: entry.uri, name: entry.name, load: signal => fileBrowserService.content(agentId, entry.uri, true, signal, selection) }
    return
  }
  const version = previewKey.value
  previewEntries.value = [{ id: entry.uri, uri: entry.uri, name: entry.name, media_type: entry.media_type, size_bytes: entry.size ?? 0 }]
  await nextTick()
  if (active && version === previewKey.value) await preview.value?.openById(entry.uri)
}
async function openUri(uri: string, revealParent = true): Promise<void> {
  uriRequest?.abort(); const request = new AbortController(); uriRequest = request
  const location = currentUri.value
  retryUri.value = uri
  uriError.value = false; uriLoading.value = true
  try {
    const entry = await fileBrowserService.info(agentId, uri, request.signal)
    if (request.signal.aborted || !active || currentUri.value !== location) return
    if (current.value) current.value.entries = current.value.entries.map(value => value.uri === uri ? entry : value)
    if (revealParent && !entry.is_collection) { const parent = parentDirectory(entry.uri); if (parent) navigate(parent, true, false) }
    await openEntry(entry, undefined, true)
  } catch { if (!request.signal.aborted && active && currentUri.value === location) uriError.value = true }
  finally { if (!request.signal.aborted && active) uriLoading.value = false }
}
function activateEntry(entry: FileEntry): void {
  if (!selection) return
  if (entry.is_collection) navigate(entry.uri)
  else if (entry.capabilities.includes('read')) { if (!selected.value.some(value => value.uri === entry.uri)) selected.value = [...selected.value, entry]; emit('confirm') }
}
function selectTree(id: string | null): void {
  if (!id) {
    const uri = currentUri.value
    expanded.value = expanded.value.includes(uri)
      ? expanded.value.filter(value => value !== uri)
      : [...expanded.value, uri]
    return
  }
  for (const scheme of schemes.value) if (id === `${scheme.scheme}://`) { navigate(id); return }
  const find = (nodes: BrowserNode[]): FileEntry | undefined => {
    for (const node of nodes) { if (node.id === id) return node.entry; const entry = find((node.children ?? []) as BrowserNode[]); if (entry) return entry }
  }
  const entry = find(treeNodes.value)
  if (entry) void openEntry(entry)
}
async function lazyLoad({ node, done, fail }: { node: BrowserNode; done: (nodes: QTreeNode[]) => void; fail: () => void }): Promise<void> {
  await load(node.entry.uri)
  if (!active) return
  if (directory(node.entry.uri).error) { fail(); navigate(node.entry.uri) }
  else done(treeNode(node.entry).children ?? [])
}
async function loadMore(_index: number, done: (stop?: boolean) => void): Promise<void> {
  if (query.value?.trim()) { await search(true); done(!searchState.value.cursor || searchState.value.error); return }
  const uri = currentUri.value
  if (!uri || unlistable.value) { done(true); return }
  const state = directory(uri)
  if (state.loading) { done(); return }
  await load(uri, state.loaded)
  done(!state.cursor || state.error || state.incomplete)
}
function refresh(): void { if (query.value?.trim()) { void search(); return }; if (currentUri.value && !unlistable.value) { previewKey.value++; void load(currentUri.value) } }
function retry(): void { if (query.value?.trim()) { void search(); return }; if (currentUri.value) void load(currentUri.value, !!current.value?.cursor) }
async function search(append = false): Promise<void> {
  if (!query.value?.trim() || !currentUri.value || (append && (searchState.value.loading || !searchState.value.cursor))) return
  searchRequest?.abort(); const request = new AbortController(); searchRequest = request
  const previous = searchState.value
  searchState.value = { ...previous, loading: true, error: false, ...(append ? {} : { entries: [], cursor: null, loaded: false }) }
  try {
    const result = await fileBrowserService.search(agentId, currentUri.value, query.value.trim(), append ? previous.cursor : null, request.signal, selection)
    if (request.signal.aborted) return
    const incomplete = result.truncated && (!result.next_cursor || append && result.next_cursor === previous.cursor)
    searchState.value = { entries: [...new Map([...(append ? previous.entries : []), ...result.entries].map(entry => [entry.uri, entry])).values()], loading: false, loaded: true, error: false, incomplete, cursor: incomplete ? null : result.next_cursor, version: previous.version + 1 }
  } catch { if (!request.signal.aborted) searchState.value = { ...searchState.value, loading: false, error: true } }
}
watch(query, () => { searchRequest?.abort(); if (query.value?.trim()) void search() })
watch(() => filePreviewOpen.value || audioPreview.value !== null || mailMessage.value !== null, value => emit('previewing', value))
watch(currentUri, async () => { await nextTick(); if (breadcrumbNav.value) breadcrumbNav.value.scrollLeft = breadcrumbNav.value.scrollWidth })
function restoreLocation(uri: string | null): void {
  audioPreview.value = null
  if ((uri ?? '') === currentUri.value) {
    target.value = null; mailMessage.value = null; previewEntries.value = []; previewKey.value++
    return
  }
  if (!uri || uri.endsWith('/')) navigate(uri ?? '', true, false)
  else { target.value = null; previewEntries.value = []; previewKey.value++; void openUri(uri) }
}
watch(() => initialUri, uri => { if (ready && active) restoreLocation(uri) })
onMounted(async () => { await loadSchemes(); ready = true; if (active) restoreLocation(initialUri) })
onBeforeUnmount(() => { active = false; schemesRequest?.abort(); searchRequest?.abort(); uriRequest?.abort() })
</script>

<style scoped>
.file-browser-container, .file-workspace { display: flex; flex: 1; flex-direction: column; min-height: 0; }
.file-workspace { overflow: hidden; border-bottom: 0; border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
.file-browser-container--dialog .file-workspace { border-left: 0; border-right: 0; border-radius: 0; }
.file-workspace > :not(.file-browser) { flex-shrink: 0; }
.file-browser { --file-divider-color: color-mix(in srgb, var(--q-dark) 10%, transparent); flex: 1; min-height: 0; }
:global(body.body--dark .file-browser) { --file-divider-color: var(--solaire-gray-accent); }
.file-browser :deep(> .q-splitter__separator) { background: var(--file-divider-color); }
.file-browser :deep(> .q-splitter__separator:hover) { background: color-mix(in srgb, var(--q-primary) 28%, transparent); }
.file-splitter-handle { display: flex; width: 20px; height: 42px; align-items: center; justify-content: center; border: 1px solid color-mix(in srgb, currentColor 18%, transparent); border-radius: 10px; color: var(--solaire-gray-accent); background: var(--q-card-background, #fff); box-shadow: 0 2px 8px rgba(35, 46, 66, .12); }
.file-splitter-handle:focus-visible { color: var(--solaire-blue-accent); outline: 2px solid var(--solaire-blue-accent); }
.file-tree { --file-tree-selection: var(--solaire-blue-light); min-width: 0; min-height: 100%; padding: 0; background: color-mix(in srgb, var(--solaire-gray-light) 50%, transparent); }
.file-tree :deep(.file-scheme-header) { min-height: 44px; padding: 6px 12px; }
.file-tree :deep(.q-tree__node--selected) { background: var(--file-tree-selection); }
.file-tree :deep(.file-scheme-selected) { background: var(--solaire-blue-light); box-shadow: inset 4px 0 var(--solaire-blue-accent); }
:global(body.body--dark .file-tree .file-scheme-selected) { background: var(--solaire-blue-dark); }
:global(body.body--dark .file-tree) { --file-tree-selection: var(--solaire-blue-dark); background: color-mix(in srgb, var(--solaire-gray-dark) 50%, transparent); }
.file-tree :deep(.q-tree__arrow), .file-tree :deep(.q-tree__spinner) { color: var(--solaire-gray-accent); }
.file-tree-entry { min-width: 0; min-height: 28px; }
.file-scheme { min-width: 0; }
.file-scheme-label { font-weight: 600; overflow-wrap: anywhere; }
.file-scheme-uri { line-height: 1.4; opacity: .8; }
.file-main { display: flex; flex-direction: column; min-width: 0; height: 100%; }
.file-toolbar { min-height: 42px; gap: 4px; }
.file-scroll { flex: 1; min-height: 0; overflow: auto; padding: 16px; }
.file-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 180px), 1fr)); align-items: start; gap: 0; }
.file-entry { position: relative; min-width: 0; }
.file-entry > :deep(.file-entry-actions) { position: absolute; top: 0; right: 0; z-index: 1; }
@media (hover: hover) {
  .file-entry > :deep(.file-entry-actions) { opacity: 0; }
  .file-entry:hover > :deep(.file-entry-actions),
  .file-entry:focus-within > :deep(.file-entry-actions),
  .file-entry > :deep(.file-entry-actions:has([aria-expanded="true"])) { opacity: 1; }
}
.file-state { padding: 60px 16px; text-align: center; }
.file-warning { background: var(--solaire-yellow-light); }
:global(body.body--dark .file-warning) { background: var(--solaire-yellow-dark); }
.file-error { --q-negative: var(--solaire-red-accent); background: var(--solaire-red-light); border: 1px solid var(--solaire-red-accent); }
:global(body.body--dark .file-error) { background: var(--solaire-red-dark); }
.file-breadcrumbs { min-width: 0; overflow-x: auto; }
.file-breadcrumbs :deep(.q-btn-group) { white-space: nowrap; }
.file-browser-container--compact .file-grid { grid-template-columns: repeat(auto-fill, minmax(min(100%, 112px), 1fr)); gap: 8px; }
.file-browser-container--compact .file-scroll { padding: 8px; }
.file-browser-container--compact .file-toolbar { min-height: 0; padding-top: 4px; padding-bottom: 0; }
.file-browser-container--compact .file-tree { font-size: 12px; }
:global(body.body--dark .file-splitter-handle) { background: var(--q-dark-page); box-shadow: 0 2px 8px rgba(0, 0, 0, .38); }
@media (max-width: 1023px) {
  .file-grid { grid-template-columns: repeat(auto-fill, minmax(min(100%, 140px), 1fr)); }
  .file-browser { flex-direction: column; }
  .file-browser :deep(> .q-splitter__before) { flex: 0 1 auto; height: auto; width: 100% !important; max-height: 40%; }
  .file-browser :deep(> .q-splitter__after) { flex: 1; min-height: 0; height: auto; }
  .file-browser :deep(> .q-splitter__separator) { display: none; }
  .file-browser--tree-hidden :deep(> .q-splitter__before),
  .file-browser--tree-hidden :deep(> .q-splitter__separator) { display: none; }
}
</style>
