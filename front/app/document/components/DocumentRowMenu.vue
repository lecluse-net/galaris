<template>
  <ActionContextMenu :target="target" :actions="actions" :label="t('documents.library.documentActions', { name: entry.item.title })">
    <template #trigger="{ toggle, open }">
      <q-btn flat dense round size="sm" color="primary" icon="more_horiz" :aria-label="t('documents.library.documentActions', { name: entry.item.title })"
        aria-haspopup="menu" :aria-expanded="open" @click="toggle" @dragstart.prevent.stop>
        <q-tooltip>{{ t('documents.library.documentActions', { name: entry.item.title }) }}</q-tooltip>
      </q-btn>
    </template>
  </ActionContextMenu>
</template>
<script setup lang="ts">
import { documentFormats, type DocumentCreationMode } from '../documentFormats'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { privileges, usePrivilegeStore } from '@/core/authorize'
import { ActionContextMenu, useResourceCopy, type ContextAction } from '@/core/util'
import type { DocumentLibraryEntry } from '../types'
import { documentRowShortcuts, type DocumentRowAction } from '@/app/document/libraryShortcuts'
const { entry, busy, target, allowCreate = false, extraActions = [] } = defineProps<{ entry: DocumentLibraryEntry; busy: boolean; target: string; allowCreate?: boolean; extraActions?: ContextAction[] }>()
const emit = defineEmits<{ select: []; create: [type?: DocumentCreationMode]; action: [value: DocumentRowAction] }>()
const { t } = useI18n()
const { action: copyAction } = useResourceCopy()
const privilegeStore = usePrivilegeStore()
const actions = computed<ContextAction[]>(() => {
  const shortcuts = documentRowShortcuts(entry, busy, () => emit('select'), allowCreate ? () => emit('create') : undefined, action => emit('action', action))
  const standard = [
    { key: 'F4', icon: 'visibility', label: t('common.open'), shortcut: 'F4' },
    { key: 'F2', icon: 'edit', label: t('documents.library.renameTag'), shortcut: 'F2' },
    { key: 'Delete', icon: 'delete', label: t('common.delete'), shortcut: 'Delete', negative: true },
  ].flatMap(action => {
    const run = shortcuts[action.key as keyof typeof shortcuts]
    return run ? [{ ...action, run }] : []
  })
  const creations = allowCreate && shortcuts.F3 && privilegeStore.hasAnyPrivilege([privileges.DOCUMENT_EDIT, privileges.DOCUMENT_ADMIN]) ? [
    ...documentFormats.map(type => ({ key: 'new-' + type.code, icon: type.icon,
      label: t('documents.createFormattedDocument', { format: t(type.label) }), run: () => emit('create', type.code) })),
    { key: 'import', icon: 'file_open', label: t('documents.importFrom'), run: () => emit('create', 'import') },
  ] : []
  return [...standard, ...extraActions, { ...copyAction(`document://${entry.item.id}`), label: t('documents.copyUrl') }, ...creations]
})
</script>
