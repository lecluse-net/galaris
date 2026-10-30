<template>
  <span class="file-entry-actions" @click.stop @dblclick.stop @keydown.enter.stop @keydown.space.stop>
    <RenameFileButton v-if="canRename" ref="renameButton" class="hidden" :name="entry.name" :rename="rename"
      :title="entry.is_collection ? t('files.renameDirectory') : ''" :name-label="entry.is_collection ? t('files.directoryName') : ''" />
    <q-btn v-if="!contextOnly" flat round dense size="sm" icon="more_vert" :aria-label="t('files.actions', { name: displayName })"
      aria-haspopup="menu" :aria-expanded="menuOpen" :disable="busy">
      <q-menu v-model="menuOpen" :transition-duration="0">
        <q-list dense role="menu" :aria-label="t('common.actions')">
          <q-item v-for="action in actions" :key="action.key" v-close-popup clickable role="menuitem" :disable="action.disabled"
            :class="{ 'text-negative': action.negative }" @click="run(action)">
            <q-item-section avatar><q-icon :name="action.icon" /></q-item-section>
            <q-item-section>{{ action.label }}</q-item-section>
          </q-item>
        </q-list>
      </q-menu>
    </q-btn>
    <ActionContextMenu :target="target" :actions="actions" @update:open="checkRepository" />
    <q-dialog v-model="confirmDelete">
      <q-card class="galaris-dialog-card" style="width: 480px; max-width: 95vw">
        <q-card-section class="galaris-dialog-title row items-center no-wrap">
          <div class="text-h6">{{ t('files.deleteTitle') }}</div><q-space />
          <q-btn v-close-popup flat round dense icon="close" :aria-label="t('common.close')" />
        </q-card-section>
        <q-card-section>
          <p>{{ t(entry.is_collection ? 'files.deleteDirectory' : 'files.deleteFile', { name: entry.name }) }}</p>
          <q-banner v-if="error" role="alert">{{ error }}<p class="q-mb-none q-mt-sm">{{ t('files.deleteError') }}</p></q-banner>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup outline :label="t('common.cancel')" />
          <q-btn color="negative" :label="t('common.delete')" :loading="busy" :disable="!canDelete" @click="remove" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </span>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'
import { copyToClipboard, useQuasar } from 'quasar'
import { useI18n } from 'vue-i18n'
import { apiErrorDetail } from '@/core/api'
import { usePrivilegeStore } from '@/core/authorize'
import { ActionContextMenu, RenameFileButton, type ContextAction } from '@/core/util'
import { fileBrowserService, type FileEntry } from '../services/fileBrowserService'
import { resourceLabel, skillCollectionLabel, executionResourceLabel } from '../presentation'

const { entry, agentId, target, open, openCode, download, contextOnly = false } = defineProps<{
  entry: FileEntry; agentId: number; target: string; open: () => unknown; openCode?: () => Promise<void>; download?: () => Promise<void>; contextOnly?: boolean
}>()
const emit = defineEmits<{ changed: [entry: FileEntry, replacement: string | null] }>()
const { t, locale } = useI18n(), $q = useQuasar(), privileges = usePrivilegeStore()
const displayName = computed(() => executionResourceLabel(entry, locale.value) ?? resourceLabel(entry, t) ?? skillCollectionLabel(entry.uri, t) ?? entry.name)
const renameButton = useTemplateRef<InstanceType<typeof RenameFileButton>>('renameButton')
const canEdit = computed(() => {
  const source = typeof entry.metadata?.rename_uri === 'string' ? entry.metadata.rename_uri : entry.uri
  const required = source.startsWith('document://') ? ['DOCUMENT_EDIT', 'DOCUMENT_ADMIN']
    : source.startsWith('data://') ? ['DATASET_EDIT', 'DATASET_ADMIN']
    : ['FILE_EDIT']
  return privileges.hasAnyPrivilege(required)
})
const canRename = computed(() => canEdit.value && fileBrowserService.canRename(entry))
const canDelete = computed(() => canEdit.value && fileBrowserService.canDelete(entry))
const busy = ref(false), confirmDelete = ref(false), error = ref('')
const menuOpen = ref(false)
const repository = ref(false)
const canOpenCode = computed(() => !!openCode && entry.is_collection && entry.uri.startsWith('console://') && privileges.hasPrivilege('CODE_ACCESS'))
let repositoryRequest: AbortController | undefined
let active = true
onBeforeUnmount(() => { active = false; repositoryRequest?.abort() })
watch(menuOpen, checkRepository)
watch(() => [agentId, entry.uri, canOpenCode.value], () => { repositoryRequest?.abort(); repository.value = false })
async function checkRepository(opened: boolean): Promise<void> {
  repositoryRequest?.abort()
  if (!opened || !canOpenCode.value) return
  repository.value = false
  const request = new AbortController(); repositoryRequest = request
  try {
    // Git checkouts use a directory marker; worktrees use a file marker.
    await fileBrowserService.info(agentId, `${entry.uri.replace(/\/?$/, '/')}.git`, request.signal)
    if (!request.signal.aborted && active) repository.value = true
  } catch { /* Ordinary directories and unavailable markers keep the regular file actions. */ }
}
async function editCode(): Promise<void> {
  if (!canOpenCode.value || busy.value || !openCode) return
  busy.value = true
  try { await openCode() }
  finally { busy.value = false }
}
async function rename(name: string): Promise<void> {
  if (!canRename.value || busy.value) return
  busy.value = true
  try {
    const replacement = await fileBrowserService.rename(agentId, entry, name)
    if (active) emit('changed', entry, replacement)
  } finally { busy.value = false }
}
async function remove(): Promise<void> {
  if (!canDelete.value || busy.value) return
  busy.value = true; error.value = ''
  try {
    await fileBrowserService.remove(agentId, entry)
    if (active) { confirmDelete.value = false; emit('changed', entry, null) }
  } catch (cause) {
    if (active) error.value = apiErrorDetail(cause) ?? t('common.anError')
  } finally { busy.value = false }
}
async function transfer(): Promise<void> {
  if (busy.value || !download) return
  busy.value = true
  try { await download() }
  catch (cause) { if (active) $q.notify({ type: 'negative', message: apiErrorDetail(cause) ?? t('common.anError') }) }
  finally { busy.value = false }
}
async function run(action: ContextAction): Promise<void> {
  const current = actions.value.find(value => value.key === action.key)
  if (!current || current.disabled) return
  try { await current.run() }
  catch (cause) { if (active) $q.notify({ type: 'negative', message: apiErrorDetail(cause) ?? t('common.anError') }) }
}
const actions = computed<ContextAction[]>(() => [
  { key: 'open', icon: 'open_in_full', label: t('common.open'), run: open },
  ...(canOpenCode.value && repository.value ? [{ key: 'code', icon: 'code', label: t('files.openCodeEditor'), disabled: busy.value, run: editCode }] : []),
  ...(download ? [{ key: 'download', icon: 'download', label: t('common.download'), disabled: busy.value, run: transfer }] : []),
  ...(canRename.value ? [{ key: 'rename', icon: 'drive_file_rename_outline', label: t('fileRename.label'), disabled: busy.value, run: () => renameButton.value?.open() }] : []),
  { key: 'copy', icon: 'content_copy', label: t('common.copyReference'), run: () => copyToClipboard(entry.uri) },
  ...(canDelete.value ? [{ key: 'delete', icon: 'delete', label: t('common.delete'), negative: true, disabled: busy.value,
    run: () => { error.value = ''; confirmDelete.value = true } }] : []),
])
</script>
