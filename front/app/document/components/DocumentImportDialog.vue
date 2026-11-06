<template>
  <q-dialog v-model="open" :maximized="$q.screen.lt.md" no-route-dismiss>
    <q-card class="document-import-dialog galaris-dialog-card column no-wrap">
      <q-card-section class="galaris-dialog-title row items-center no-wrap">
        <q-icon name="file_download" size="24px" class="q-mr-sm" />
        <div class="text-h6">{{ t('documents.imports.title') }}</div><q-space />
        <q-btn flat round dense icon="close" :aria-label="t('common.close')" @click="open = false" />
      </q-card-section>
      <q-card-section class="import-body col scroll" @dragover.prevent @drop.prevent="dropFiles">
        <q-banner rounded class="q-mb-md" :style="{ background: solaireCss.blue[$q.dark.isActive ? 'dark' : 'light'] }">
          <template #avatar><q-icon name="info" :style="{ color: solaireCss.blue.accent }" /></template>
          <p class="q-mb-xs">{{ t('documents.imports.infoFormats') }}</p>
          <p class="q-mb-xs">{{ t('documents.imports.infoWorkflow') }}</p>
          <p class="q-mb-none">{{ t('documents.imports.infoArchive') }}</p>
        </q-banner>
        <q-banner v-if="loadError" role="alert" class="q-mb-md">{{ t('documents.imports.loadError') }}
          <q-btn outline color="primary" :label="t('common.retry')" @click="loadOptions" />
        </q-banner>
        <div class="import-sources q-mb-md">
          <q-file :model-value="[]" outlined dense multiple :disable="busy" :label="t('documents.imports.localFiles')" @update:model-value="addLocalFiles">
            <template #prepend><q-icon name="upload_file" /></template>
          </q-file>
          <q-btn outline color="primary" icon="folder_open" :disable="busy" :label="t('documents.imports.sharedFiles')" @click="pickerOpen = true" />
        </div>
        <q-table v-model:pagination="pagination" flat bordered :rows="items" :columns="columns" row-key="key" :loading="loading"
          :rows-per-page-options="[10, 20, 50, 100, 500]" :rows-per-page-label="t('documents.library.pageSize')" :no-data-label="t('documents.imports.empty')">
          <template #body-cell-name="cell"><q-td :props="cell" class="import-name" :title="cell.row.name">{{ cell.row.name }}
            <div v-if="isArchive(cell.row)">
              <q-select outlined dense emit-value map-options :model-value="cell.row.archiveMode ?? 'file'" :options="archiveOptions" :disable="busy" :label="t('documents.imports.archiveMode')" @update:model-value="cell.row.archiveMode = $event === 'file' ? null : $event" />
            </div>
            <div v-if="isArchive(cell.row) && cell.row.archiveMode" class="text-caption">{{ t('documents.imports.archiveDestination', { name: archiveParent(cell.row)?.name ?? t('documents.library.root') }) }}</div>
            <div v-if="isArchive(cell.row) && cell.row.archiveMode === 'subfolder'" class="text-caption">{{ t('documents.imports.archiveFolderName', { name: cell.row.title.slice(0, 100) }) }}</div>
          </q-td></template>
          <template #body-cell-compatible="cell"><q-td :props="cell">
            <span v-if="!formats">—</span>
            <span v-else><q-icon :name="importable(cell.row) ? 'check_circle' : 'cancel'" :color="importable(cell.row) ? 'positive' : 'negative'" class="q-mr-xs" />{{ t(importable(cell.row) ? 'documents.imports.yes' : 'documents.imports.no') }}</span>
          </q-td></template>
          <template #body-cell-status="cell"><q-td :props="cell">
            <q-spinner v-if="cell.row.status === 'running'" color="primary" class="q-mr-xs" />
            <span role="status">{{ t(`documents.imports.states.${formats && cell.row.status === 'pending' && !importable(cell.row) ? 'unsupported' : cell.row.status}`) }}</span>
            <div v-if="cell.row.error" role="alert" class="text-negative import-error">{{ cell.row.error }}</div>
          </q-td></template>
          <template #body-cell-actions="cell"><q-td :props="cell">
            <q-btn flat round dense color="negative" icon="close" :disable="busy" :aria-label="t('documents.imports.removeFile', { name: cell.row.name })" @click="items = items.filter(value => value.key !== cell.row.key)" />
          </q-td></template>
        </q-table>
        <p v-if="busy" role="status" class="text-caption q-mt-md">{{ t('documents.importingFile', { name: currentFile }) }}</p>
      </q-card-section>
      <q-separator />
      <q-card-actions class="galaris-dialog-actions" align="right">
        <q-btn outline color="primary" icon="clear_all" :disable="busy || !items.length" :label="t('documents.imports.clearList')" @click="items = []" />
        <q-space />
        <q-btn outline color="primary" :label="t('common.close')" @click="open = false" />
        <q-btn color="primary" icon="file_download" :loading="busy" :disable="!canRun" :label="t('documents.imports.start', { count: pending.length })" @click="run" />
      </q-card-actions>
    </q-card>
  </q-dialog>
  <ResourcePicker v-model="pickerOpen" :agent-id="agentId" :title="t('documents.imports.sharedFiles')" @select="addSharedFiles" />
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { isAxiosError } from 'axios'
import { useQuasar, type QTableColumn } from 'quasar'
import { AUTH_TOKEN_CHANGED_EVENT, apiErrorDetail, sessionGeneration } from '@/core/api'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { solaireCss } from '@/core/util'
import ResourcePicker from '@/resourcePicker.vue'
import importMessages from '../importI18n'
import { documentService } from '../services/documentService'
import type { DocumentArchiveContents, DocumentLibraryEntry, DocumentOwnerOption, DocumentRecord, DocumentTag } from '../types'
interface ImportItem {
  key: string; name: string; mime: string; title: string; file?: File; source?: { uri: string; agent_id: number }
  status: 'pending' | 'running' | 'error'; error: string; retryable: boolean
  archiveMode: 'folder' | 'subfolder' | null; destination?: DocumentTag | null
  archive?: DocumentArchiveContents & { folders: Record<'folder' | 'subfolder', Map<string, DocumentTag | null>> }
}
const props = defineProps<{
  files: File[]; agentId: number | null; tag: DocumentTag | null; parent: DocumentLibraryEntry | null; atRoot: boolean
  complete: (document: DocumentRecord, actor: number | null, tag: DocumentTag | null, parent: DocumentLibraryEntry | null, atRoot: boolean) => Promise<void>
}>()
const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ progress: [name: string]; filesConsumed: []; structureChanged: [] }>()
const { t, locale, mergeLocaleMessage } = useI18n(), privilegeStore = usePrivilegeStore(), $q = useQuasar()
function registerImportMessages(): void {
  for (const [language, messages] of Object.entries(importMessages)) mergeLocaleMessage(language, messages)
}
watch(locale, registerImportMessages, { immediate: true, flush: 'sync' })
const items = ref<ImportItem[]>([]), pickerOpen = ref(false), busy = ref(false), currentFile = ref('')
const owner = ref<DocumentOwnerOption | null>(null), formats = ref<{ extensions: string[]; media_types: string[] } | null>(null)
const loading = ref(false), loadError = ref(false), pagination = ref({ page: 1, rowsPerPage: 50 })
const archiveOptions = computed(() => [
  { value: 'file', label: t('documents.imports.archiveFile') },
  { value: 'folder', label: t('documents.imports.archiveCurrent') },
  { value: 'subfolder', label: t('documents.imports.archiveSubfolder') },
])
const columns = computed<QTableColumn<ImportItem>[]>(() => [
  { name: 'name', label: t('documents.imports.name'), field: 'name', align: 'left' },
  { name: 'format', label: t('documents.imports.format'), field: item => item.name.match(/\.([^.]+)$/)?.[1]?.toUpperCase() ?? item.mime, align: 'left' },
  { name: 'compatible', label: t('documents.imports.compatible'), field: 'name', align: 'left' },
  { name: 'status', label: t('documents.imports.status'), field: 'status', align: 'left' },
  { name: 'actions', label: '', field: 'key', align: 'right' },
])
function isArchive(item: { name: string; mime: string; source?: { uri: string } }): boolean {
  return !/^(document|data):\/\/[^/]+$/.test(item.source?.uri ?? '')
    && (/\.zip$/i.test(item.name) || ['application/zip', 'application/x-zip-compressed'].includes(item.mime))
}
function archiveParent(item: ImportItem): DocumentTag | null { return item.destination !== undefined ? item.destination : props.tag ?? props.parent?.tags?.[0] ?? null }
function importable(item: ImportItem): boolean {
  if (isArchive(item) && item.archiveMode) return true
  if (/^(document|data):\/\/[^/]+$/.test(item.source?.uri ?? '')) return true
  const suffix = item.name.match(/\.[^.]+$/)?.[0]?.toLowerCase()
  return !!formats.value && (formats.value.extensions.includes(suffix ?? '') || formats.value.media_types.includes(item.mime.split(';')[0]?.trim().toLowerCase() ?? ''))
}
const pending = computed(() => items.value.filter(item => item.status === 'pending' || item.status === 'error' && item.retryable))
const canRun = computed(() => !busy.value && !loading.value && !!owner.value && pending.value.length > 0
  && privilegeStore.hasAnyPrivilege([privileges.DOCUMENT_EDIT, privileges.DOCUMENT_ADMIN]))
let disposed = false, optionsGeneration = 0
async function loadOptions(): Promise<void> {
  const generation = ++optionsGeneration
  loading.value = true; loadError.value = false
  try {
    const [choices, supported] = await Promise.all([documentService.listDocumentOwnerOptions(), documentService.importFormats()])
    if (disposed || generation !== optionsGeneration) return
    owner.value = choices.users.find(value => value.is_current_user) ?? choices.agents.find(value => value.id === props.agentId) ?? choices.agents[0] ?? null
    formats.value = supported
  } catch { if (!disposed && generation === optionsGeneration) loadError.value = true }
  finally { if (generation === optionsGeneration) loading.value = false }
}
function addLocalFiles(value: File | File[] | null): void {
  if (busy.value) return
  for (const file of value ? Array.isArray(value) ? value : [value] : []) {
    if (items.value.some(item => item.file?.name === file.name && item.file.size === file.size && item.file.lastModified === file.lastModified)) continue
    items.value.push({ key: crypto.randomUUID(), name: file.name, mime: file.type, title: (file.name.replace(/\.[^.]+$/, '') || file.name).slice(0, 500),
      file, status: 'pending', error: '', retryable: false, archiveMode: isArchive({ name: file.name, mime: file.type }) ? 'subfolder' : null })
  }
}
function dropFiles(event: DragEvent): void { if (event.dataTransfer) addLocalFiles(Array.from(event.dataTransfer.files)) }
function addSharedFiles(files: { uri: string; name: string; media_type?: string; is_collection: boolean }[], agent: number): void {
  for (const file of files.filter(value => !value.is_collection)) {
    if (items.value.some(item => item.source?.uri === file.uri)) continue
    items.value.push({ key: crypto.randomUUID(), name: file.name, mime: file.media_type ?? '', title: (file.name.replace(/\.[^.]+$/, '') || file.name).slice(0, 500),
      source: { uri: file.uri, agent_id: agent }, status: 'pending', error: '', retryable: false, archiveMode: isArchive({ name: file.name, mime: file.media_type ?? '', source: { uri: file.uri } }) ? 'subfolder' : null })
  }
  pickerOpen.value = false
}
async function expandArchive(item: ImportItem, active: () => boolean): Promise<ImportItem[]> {
  const mode = item.archiveMode
  if (!mode) return []
  if (!item.archive) {
    const contents = await documentService.expandArchive(item.file, item.source)
    if (!active()) return []
    item.archive = { ...contents, folders: { folder: new Map(), subfolder: new Map() } }
  }
  const archive = item.archive
  const folders = archive.folders[mode]
  if (mode === 'folder' && !folders.has('')) folders.set('', archiveParent(item))
  let changed = false
  try {
    for (const path of ['', ...archive.directories]) {
      if (!active()) return []
      if (folders.has(path)) continue
      const parentPath = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
      const parent = path ? folders.get(parentPath)?.id ?? null : archiveParent(item)?.id ?? null
      currentFile.value = path ? `${item.name}/${path}` : item.name; emit('progress', currentFile.value)
      const folder = await documentService.saveDocumentTag({ name: (path.split('/').at(-1) || item.title).slice(0, 100), parent_id: parent })
      folders.set(path, folder); changed = true
    }
  } finally { if (changed && active()) emit('structureChanged') }
  return archive.files.map(({ path, file }) => ({ key: crypto.randomUUID(), name: `${item.name}/${path}`, mime: file.type,
    title: (file.name.replace(/\.[^.]+$/, '') || file.name).slice(0, 500), file, status: 'pending', error: '', retryable: false,
    archiveMode: null, destination: folders.get(path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '')! }))
}
async function run(): Promise<void> {
  const selectedOwner = owner.value
  if (!canRun.value || !selectedOwner) return
  const session = sessionGeneration(), batch = [...pending.value]
  const tag = props.tag, parent = props.parent, atRoot = props.atRoot
  const active = () => !disposed && session === sessionGeneration()
  busy.value = true
  try {
    for (const item of batch) {
      if (!active() || !privilegeStore.hasAnyPrivilege([privileges.DOCUMENT_EDIT, privileges.DOCUMENT_ADMIN])) break
      item.status = 'running'; item.error = ''; currentFile.value = item.name; emit('progress', item.name)
      const actor = selectedOwner.kind === 'agent' ? selectedOwner.id : null
      const request = { owner_kind: selectedOwner.kind, owner_id: selectedOwner.id, actor_agent_id: actor, title: item.title.trim(), folder: '' }
      try {
        if (isArchive(item) && item.archiveMode) {
          const entries = await expandArchive(item, active)
          if (!active()) break
          const index = items.value.findIndex(value => value.key === item.key)
          items.value.splice(index, 1, ...entries)
          batch.push(...entries)
          continue
        }
        const document = item.file ? await documentService.importDocument(request, item.file)
          : await documentService.createDocument({ ...request, import_from: item.source })
        if (!active()) break
        item.file = undefined
        const placed = item.destination !== undefined
        try { await props.complete(document, actor, placed ? item.destination ?? null : tag, placed ? null : parent, placed ? item.destination === null : atRoot) }
        catch { if (active()) $q.notify({ type: 'warning', message: t('documents.imports.openError') }) }
        items.value = items.value.filter(value => value.key !== item.key)
      } catch (error) {
        if (!active()) break
        item.status = 'error'
        const status = isAxiosError(error) ? error.response?.status : undefined
        item.retryable = status !== undefined && status >= 400 && status < 500
        item.error = status === 415 ? t('documents.importUnsupported') : apiErrorDetail(error) ?? t('documents.importError')
        if (!item.retryable) item.error += ' ' + t('documents.imports.checkLibrary')
      }
    }
  } finally { busy.value = false; currentFile.value = ''; if (!disposed) emit('progress', '') }
}
watch(() => props.files, files => { addLocalFiles(files); if (files.length) emit('filesConsumed') }, { immediate: true })
watch(open, value => { if (value && !busy.value) void loadOptions() }, { immediate: true })
function resetSession(): void { open.value = false; pickerOpen.value = false; items.value = []; owner.value = null; formats.value = null; ++optionsGeneration }
window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, resetSession)
onBeforeUnmount(() => { disposed = true; ++optionsGeneration; window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, resetSession) })
</script>
<style scoped>
.document-import-dialog { width: 880px; max-width: calc(100vw - 32px); max-height: calc(100dvh - 32px); }
.import-body { min-height: 0; }
.import-sources { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-auto-rows: 1fr; gap: 8px; }
.import-name, .import-error { white-space: normal; overflow-wrap: anywhere; }
.import-name { min-width: 260px; }
@media (max-width: 1023.98px) { .document-import-dialog { width: 100%; max-width: 100%; max-height: 100dvh; } }
@media (max-width: 599.98px) { .import-sources { grid-template-columns: 1fr; } }
</style>
