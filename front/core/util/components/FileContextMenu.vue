<template>
  <RenameFileButton v-if="rename" ref="renameButton" :class="renameClass" :name="name" :rename="rename" />
  <ActionContextMenu :class="menuClass" :target="target" :actions="actions" />
</template>
<script setup lang="ts">
import { computed, ref, useTemplateRef } from 'vue'
import { copyToClipboard } from 'quasar'
import { useI18n } from 'vue-i18n'
import ActionContextMenu from './ActionContextMenu.vue'
import RenameFileButton from './RenameFileButton.vue'
import type { ContextAction } from '../contextActions'
const { name, uri, target, open, download, rename, renameClass = '', menuClass = '', extraActions = [] } = defineProps<{
  name: string; uri?: string; target: string; open: () => unknown; download?: () => unknown;
  rename?: (name: string) => Promise<unknown>; renameClass?: string; menuClass?: string; extraActions?: ContextAction[]
}>()
const { t } = useI18n()
const renameButton = useTemplateRef<InstanceType<typeof RenameFileButton>>('renameButton')
const busy = ref(false)
async function transfer(): Promise<void> {
  if (busy.value || !download) return
  busy.value = true
  try { await download() } finally { busy.value = false }
}
const actions = computed<ContextAction[]>(() => [
  { key: 'open', icon: 'open_in_full', label: t('common.open'), run: open },
  ...(download ? [{ key: 'download', icon: 'download', label: t('common.download'), disabled: busy.value, run: transfer }] : []),
  ...(rename ? [{ key: 'rename', icon: 'drive_file_rename_outline', label: t('fileRename.label'), run: () => renameButton.value?.open() }] : []),
  ...(uri ? [{ key: 'copy', icon: 'content_copy', label: t('common.copyReference'), run: () => copyToClipboard(uri) }] : []),
  ...extraActions,
])
</script>
