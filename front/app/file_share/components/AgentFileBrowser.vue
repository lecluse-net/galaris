<template>
  <div class="file-browser-container">
    <q-card flat bordered class="file-workspace">
    <q-splitter v-model="split" :limits="[18, 45]" :disable="$q.screen.lt.md" class="file-browser" :class="{ 'file-browser--tree-hidden': $q.screen.lt.md && !showTree }">
      <template #before>
      <aside class="file-tree" :aria-label="t('files.tree')">
        <div class="text-subtitle2 q-px-sm q-mb-sm">{{ t('files.roots') }}</div>
        <q-spinner v-if="schemesLoading" color="primary" />
        <q-list v-else>
          <q-expansion-item v-for="root in treeNodes" :key="root.id" :model-value="openScheme === root.id"
            :header-class="{ 'file-scheme-selected': currentUri.startsWith(root.id) }"
            hide-expand-icon :toggle-aria-label="root.label" :duration="0" @update:model-value="toggleScheme(root.id, $event)">
            <template #header>
              <div class="file-scheme full-width" :title="root.id">
                <div class="file-scheme-label">{{ root.label }}</div>
                <div class="file-scheme-uri text-caption text-grey-7">{{ root.scheme }}://</div>
              </div>
            </template>
            <div v-if="!root.disabledRoot" class="q-px-sm q-pb-sm">
                <q-spinner v-if="directory(root.id).loading" color="primary" :aria-label="t('files.loading')" />
                <q-tree v-if="root.children?.length" :nodes="root.children" node-key="id" :selected="currentUri" :expanded="expanded" dense no-transition
                  :text-color="$q.dark.isActive ? 'white' : 'dark'" :selected-color="$q.dark.isActive ? 'white' : 'dark'"
                  @update:expanded="expanded = [...$event]" @update:selected="selectTree" @lazy-load="lazyLoad">
                  <template #default-header="scope">
                    <div class="file-tree-entry row items-center no-wrap full-width" :title="scope.node.entry.uri">
                      <FolderIcon tone="orange" :expanded="scope.expanded" size="26px" class="q-mr-xs" />
                      <span class="ellipsis">{{ scope.node.label }}</span>
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
        <q-toolbar class="file-toolbar q-px-sm q-gutter-sm">
          <q-btn class="lt-md" round outline color="primary" size="sm" icon="account_tree" :aria-label="t('files.toggleTree')" @click="showTree = !showTree">
            <q-tooltip>{{ t('files.toggleTree') }}</q-tooltip>
          </q-btn>
          <q-btn round outline color="primary" size="sm" icon="arrow_back" :aria-label="t('files.up')" :disable="!parent" @click="parent && navigate(parent)">
            <q-tooltip>{{ t('files.up') }}</q-tooltip>
          </q-btn>
          <q-breadcrumbs class="col file-breadcrumbs" gutter="xs">
            <template #separator><q-icon name="chevron_right" size="18px" color="grey-6" /></template>
            <q-breadcrumbs-el v-for="(crumb, index) in breadcrumbs" :key="crumb.uri">
              <q-btn rounded dense no-caps color="primary" :outline="crumb.uri !== currentUri" :unelevated="crumb.uri === currentUri"
                padding="4px 12px" :icon="index === 0 ? 'storage' : 'folder_open'" :label="crumb.label"
                :aria-current="crumb.uri === currentUri ? 'location' : undefined" @click="navigate(crumb.uri)">
                <q-tooltip>{{ crumb.uri }}</q-tooltip>
              </q-btn>
            </q-breadcrumbs-el>
          </q-breadcrumbs>
          <q-btn round unelevated color="primary" size="sm" icon="refresh" :aria-label="t('files.refresh')" :disable="!currentUri" :loading="current?.loading" @click="refresh">
            <q-tooltip>{{ t('files.refresh') }}</q-tooltip>
          </q-btn>
        </q-toolbar>
        <q-separator />
        <div ref="scroll" class="file-scroll" tabindex="0" :aria-label="t('files.title')">
          <q-banner v-if="schemesError" role="alert" class="file-error">
            <template #avatar><q-icon name="error" color="negative" /></template>
            {{ t('files.loadError') }}
            <template #action><q-btn color="negative" :label="t('common.retry')" @click="loadSchemes" /></template>
          </q-banner>
          <div v-else-if="!currentUri" class="file-state">{{ t('files.selectRoot') }}</div>
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
            <q-infinite-scroll :key="currentUri" :scroll-target="scroll || undefined" :disable="current.error || current.incomplete || (current.loaded && !current.cursor)" :offset="180" @load="loadMore">
              <div class="file-grid">
                <FileTile v-for="entry in sortedEntries" :key="`${entry.uri}:${current.version}`" :entry="entry" :agent-id="agentId" @open="openEntry" />
              </div>
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
    <ResourceDetailDialog v-if="target" :target="target" @close="target = null" @changed="refresh" />
    <ResourceAttachments ref="preview" :key="previewKey" :resource-id="String(agentId)" :agent-id="agentId" :attachments="previewEntries"
      :resource-source="previewSource" preview-only />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuasar, type QTreeNode } from 'quasar'
import { FolderIcon, ResourceAttachments, ResourceDetailDialog, type ResourceDetailTarget, type AttachmentSource, type ResourceAttachment } from '@/core/util'
import { fileBrowserService, type FileEntry, type FileScheme } from '../services/fileBrowserService'
import { useFileDirectories } from '../browserState'
import { parentDirectory, resourceTarget } from '../presentation'
import FileTile from './FileTile.vue'

const { agentId } = defineProps<{ agentId: number }>()
const { t, locale } = useI18n()
const $q = useQuasar()
const { directory, load } = useFileDirectories(agentId)
const schemes = ref<FileScheme[]>([])
const schemesLoading = ref(false), schemesError = ref(false)
const currentUri = ref(''), showTree = ref(false), expanded = ref<string[]>([])
const openScheme = ref<string | null>(null)
const split = ref(24)
const target = ref<ResourceDetailTarget | null>(null)
const preview = useTemplateRef<{ openById: (id: string) => Promise<void> }>('preview')
const previewEntries = ref<ResourceAttachment[]>([]), previewKey = ref(0)
const scroll = useTemplateRef<HTMLElement>('scroll')
let schemesRequest: AbortController | undefined
let active = true
const current = computed(() => currentUri.value ? directory(currentUri.value) : null)
const parent = computed(() => parentDirectory(currentUri.value))
const unlistable = computed(() => schemes.value.some(scheme => `${scheme.scheme}://` === currentUri.value && (!scheme.capabilities.includes('list') || scheme.root_listable === false)))
const sortedEntries = computed(() => (current.value?.entries ?? []).filter(isVisible).sort((a, b) => Number(b.is_collection) - Number(a.is_collection) || a.name.localeCompare(b.name, locale.value)))
const loadedCount = computed(() => schemesError.value || unlistable.value ? 0 : sortedEntries.value.length)
defineExpose({ loadedCount })
const previewSource: AttachmentSource = {
  content: (entry, convert, signal) => fileBrowserService.content(agentId, entry.id, convert, signal),
}
const breadcrumbs = computed(() => {
  const crumbs: { uri: string; label: string }[] = []
  let uri: string | null = currentUri.value
  while (uri) {
    const path = uri.replace(/\/$/, '')
    let label = path.includes('://') && !path.endsWith(':/') ? path.split('/').at(-1) || uri : uri
    try { label = decodeURIComponent(label) } catch { /* Keep the provider's original label. */ }
    crumbs.unshift({ uri, label })
    uri = parentDirectory(uri)
  }
  return crumbs
})
interface BrowserNode extends QTreeNode { id: string; entry: FileEntry; disabledRoot?: boolean; scheme?: string }
function isVisible(entry: FileEntry): boolean { return !entry.name.startsWith('.') }
function treeNode(entry: FileEntry, ancestors: Set<string> = new Set()): BrowserNode {
  const state = directory(entry.uri)
  const disabledRoot = schemes.value.some(scheme => `${scheme.scheme}://` === entry.uri && (!scheme.capabilities.includes('list') || scheme.root_listable === false))
  const node: BrowserNode = { id: entry.uri, label: entry.name, entry, disabledRoot,
    icon: entry.is_collection ? 'folder' : 'insert_drive_file', lazy: entry.is_collection && !disabledRoot && !state.loaded }
  if (entry.is_collection && state.loaded && !ancestors.has(entry.uri) && ancestors.size < 64) {
    const next = new Set([...ancestors, entry.uri])
    node.children = state.entries.filter(child => child.is_collection && isVisible(child)).map(child => treeNode(child, next))
  }
  return node
}
const treeNodes = computed(() => schemes.value.map(scheme => ({ ...treeNode({ uri: `${scheme.scheme}://`,
  name: scheme.label, is_collection: true, media_type: '', size: null, capabilities: scheme.capabilities }), scheme: scheme.scheme })))
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
function navigate(uri: string, closeTree = true): void {
  currentUri.value = uri
  const root = treeNodes.value.find(root => uri.startsWith(root.id))
  openScheme.value = root?.id ?? null
  if (root && root.id !== uri && !root.disabledRoot && !directory(root.id).loaded && !directory(root.id).error) void load(root.id)
  if (scroll.value) scroll.value.scrollTop = 0
  const reveal = (): void => {
    if (!active || currentUri.value !== uri || !directory(uri).loaded) return
    const ancestors: string[] = []
    for (let current: string | null = uri; current; current = parentDirectory(current)) ancestors.push(current)
    expanded.value = [...new Set([...expanded.value, ...ancestors])]
  }
  if (!unlistable.value && !directory(uri).loaded && !directory(uri).error) void load(uri).then(reveal)
  else reveal()
  if (closeTree && $q.screen.lt.md) showTree.value = false
}
async function openEntry(entry: FileEntry): Promise<void> {
  if (entry.is_collection) { navigate(entry.uri); return }
  target.value = resourceTarget(entry, agentId)
  if (target.value) return
  previewEntries.value = [{ id: entry.uri, uri: entry.uri, name: entry.name, media_type: entry.media_type, size_bytes: entry.size ?? 0 }]
  await nextTick()
  if (active) await preview.value?.openById(entry.uri)
}
function selectTree(id: string | null): void {
  if (!id) return
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
  const uri = currentUri.value
  if (!uri || unlistable.value) { done(true); return }
  const state = directory(uri)
  if (state.loading) { done(); return }
  await load(uri, state.loaded)
  done(!state.cursor || state.error || state.incomplete)
}
function refresh(): void { if (currentUri.value && !unlistable.value) { previewKey.value++; void load(currentUri.value) } }
function retry(): void { if (currentUri.value) void load(currentUri.value, !!current.value?.cursor) }
onMounted(() => { void loadSchemes() })
onBeforeUnmount(() => { active = false; schemesRequest?.abort() })
</script>

<style scoped>
.file-browser-container, .file-workspace { display: flex; flex: 1; flex-direction: column; min-height: 0; }
.file-workspace { overflow: hidden; border-bottom: 0; border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
.file-workspace > :not(.file-browser) { flex-shrink: 0; }
.file-browser { flex: 1; min-height: 0; }
.file-browser :deep(> .q-splitter__separator) { background: color-mix(in srgb, var(--q-dark) 10%, transparent); }
.file-browser :deep(> .q-splitter__separator:hover) { background: color-mix(in srgb, var(--q-primary) 28%, transparent); }
.file-splitter-handle { display: flex; width: 20px; height: 42px; align-items: center; justify-content: center; border: 1px solid color-mix(in srgb, currentColor 18%, transparent); border-radius: 10px; color: var(--solaire-gray-accent); background: var(--q-card-background, #fff); box-shadow: 0 2px 8px rgba(35, 46, 66, .12); }
.file-splitter-handle:focus-visible { color: var(--solaire-blue-accent); outline: 2px solid var(--solaire-blue-accent); }
.file-tree { --file-tree-selection: var(--solaire-gray-light); min-width: 0; padding: 12px 0; }
.file-tree :deep(.q-tree__node--selected), .file-tree :deep(.file-scheme-selected) { background: var(--file-tree-selection); }
:global(body.body--dark .file-tree) { --file-tree-selection: var(--solaire-gray-dark); }
.file-tree :deep(.q-tree__arrow), .file-tree :deep(.q-tree__spinner) { color: var(--solaire-gray-accent); }
.file-tree-entry { min-width: 0; min-height: 28px; }
.file-scheme { min-width: 0; padding: 4px 0; }
.file-scheme-label { font-weight: 600; overflow-wrap: anywhere; }
.file-scheme-uri { line-height: 1.4; }
.file-main { display: flex; flex-direction: column; min-width: 0; height: 100%; }
.file-scroll { flex: 1; min-height: 0; overflow: auto; padding: 16px; }
.file-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 180px), 1fr)); align-items: start; gap: 14px; }
.file-state { padding: 60px 16px; text-align: center; }
.file-warning { background: var(--solaire-yellow-light); }
:global(body.body--dark .file-warning) { background: var(--solaire-yellow-dark); }
.file-error { --q-negative: var(--solaire-red-accent); background: var(--solaire-red-light); border: 1px solid var(--solaire-red-accent); }
:global(body.body--dark .file-error) { background: var(--solaire-red-dark); }
.file-breadcrumbs { min-width: 0; overflow-wrap: anywhere; }
:global(body.body--dark .file-splitter-handle) { background: var(--q-dark-page); box-shadow: 0 2px 8px rgba(0, 0, 0, .38); }
@media (max-width: 1023px) {
  .file-browser { flex-direction: column; }
  .file-browser :deep(> .q-splitter__before) { flex: 0 1 auto; height: auto; width: 100% !important; max-height: 40%; }
  .file-browser :deep(> .q-splitter__after) { flex: 1; min-height: 0; height: auto; }
  .file-browser :deep(> .q-splitter__separator) { display: none; }
  .file-browser--tree-hidden :deep(> .q-splitter__before),
  .file-browser--tree-hidden :deep(> .q-splitter__separator) { display: none; }
}
</style>
